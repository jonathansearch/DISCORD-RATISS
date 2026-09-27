#!/usr/bin/env python3
"""Supprime uniquement les messages envoyés par les webhooks RATISS aujourd'hui.

Sécurité :
- aperçu par défaut ; --execute est obligatoire pour supprimer ;
- ne cible que les messages dont webhook_id correspond à un webhook RATISS ;
- ne supprime jamais les messages ordinaires des utilisateurs ;
- les URLs et tokens ne sont jamais affichés.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

API = "https://discord.com/api/v10"
SECRET_NAMES = ("RATISS",) + tuple(f"RATISS{i}" for i in range(2, 24))
WEBHOOK_RE = re.compile(r"^https://(?:discord\.com|discordapp\.com)/api/webhooks/(\d+)/([^/?]+)")
LOCAL_ZONE = ZoneInfo("Africa/Douala")


def api(method: str, url: str, token: str, payload: dict | None = None) -> object:
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Authorization": f"Bot {token}", "User-Agent": "RATISS-purge/1.0"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        body = exc.read()[:300].decode(errors="replace")
        raise RuntimeError(f"Discord HTTP {exc.code}: {body}") from exc


def webhook_info(webhook_url: str) -> tuple[str, str, str]:
    match = WEBHOOK_RE.match(webhook_url.strip())
    if not match:
        raise RuntimeError("un webhook RATISS n'est pas une URL Discord valide")
    webhook_id, webhook_token = match.groups()
    req = urllib.request.Request(
        f"{API}/webhooks/{webhook_id}/{webhook_token}",
        headers={"User-Agent": "RATISS-purge/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            info = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"webhook inaccessible (HTTP {exc.code})") from exc
    channel_id = str(info.get("channel_id") or "")
    guild_id = str(info.get("guild_id") or "@me")
    if not channel_id:
        raise RuntimeError("le webhook ne fournit aucun channel_id")
    return webhook_id, channel_id, guild_id


def parse_day(value: str | None) -> tuple[datetime, datetime, str]:
    target = date.fromisoformat(value) if value else datetime.now(LOCAL_ZONE).date()
    start_local = datetime.combine(target, time.min, tzinfo=LOCAL_ZONE)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc), target.isoformat()


def message_time(message: dict) -> datetime:
    return datetime.fromisoformat(message["timestamp"].replace("Z", "+00:00"))


def collect_webhooks() -> list[tuple[str, str]]:
    values = []
    for name in SECRET_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            values.append((name, value))
    if not values:
        raise RuntimeError("aucun secret RATISS à RATISS23 n'est configuré")
    return values


def messages_today(token: str, channel_id: str, webhook_id: str, start: datetime, end: datetime) -> list[dict]:
    found: list[dict] = []
    before: str | None = None
    while True:
        query = {"limit": "100"}
        if before:
            query["before"] = before
        url = f"{API}/channels/{channel_id}/messages?{urllib.parse.urlencode(query)}"
        messages = api("GET", url, token)
        if not isinstance(messages, list) or not messages:
            break
        reached_before_start = False
        for message in messages:
            created = message_time(message)
            if created < start:
                reached_before_start = True
                break
            if start <= created < end and str(message.get("webhook_id", "")) == webhook_id:
                found.append(message)
        if reached_before_start or len(messages) < 100:
            break
        before = str(messages[-1]["id"])
    return found


def delete_messages(token: str, channel_id: str, messages: list[dict], execute: bool) -> int:
    ids = [str(m["id"]) for m in messages]
    if not ids:
        return 0
    if not execute:
        return len(ids)
    deleted = 0
    for offset in range(0, len(ids), 100):
        batch = ids[offset:offset + 100]
        if len(batch) == 1:
            api("DELETE", f"{API}/channels/{channel_id}/messages/{batch[0]}", token)
        else:
            api("POST", f"{API}/channels/{channel_id}/messages/bulk-delete", token, {"messages": batch})
        deleted += len(batch)
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="date locale Africa/Douala au format YYYY-MM-DD ; défaut : aujourd'hui")
    parser.add_argument("--execute", action="store_true", help="effectue réellement la suppression")
    args = parser.parse_args()
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("ERREUR : le secret DISCORD_BOT_TOKEN est absent.", file=sys.stderr)
        return 2
    start, end, day = parse_day(args.date)
    try:
        configured = collect_webhooks()
        seen: set[tuple[str, str]] = set()
        total = 0
        print(f"Mode : {'SUPPRESSION' if args.execute else 'APERÇU'} | Date : {day} | Fuseau : Africa/Douala")
        for secret_name, url in configured:
            webhook_id, channel_id, guild_id = webhook_info(url)
            key = (webhook_id, channel_id)
            if key in seen:
                continue
            seen.add(key)
            messages = messages_today(token, channel_id, webhook_id, start, end)
            count = delete_messages(token, channel_id, messages, args.execute)
            total += count
            print(f"{secret_name}: {count} message(s) RATISS {'supprimé(s)' if args.execute else 'ciblé(s)'}")
            if args.execute:
                for message in messages:
                    print(f"  message supprimé : https://discord.com/channels/{guild_id}/{channel_id}/{message['id']}")
        print(f"TOTAL : {total}")
        return 0
    except (RuntimeError, ValueError, KeyError) as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
