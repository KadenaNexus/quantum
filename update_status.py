#!/usr/bin/env python3
"""
Backend job for the Quantum-Safe Kadena page.

Every run does two things:

1. Polls the GitHub REST API for the post-quantum work in the Kadena community
   repositories and writes status.json (live facts: latest commits, PR states,
   latest release).

2. Evaluates the rules in assessment.json against those facts and raises each
   milestone's "auto" score when a rule is satisfied. The page shows
   max(done, auto) per milestone, so the bar moves up on its own when real
   events happen (a PR is merged, a TODO disappears from a file, a release is
   tagged) and never moves down. The hand-set "done" values are never changed
   by this job.

Usage:
    python3 update_status.py /var/www/quantum.kadena.ws

(the argument is the folder that holds index.html, assessment.json, status.json)

Environment (optional):
    GITHUB_TOKEN   a fine-grained read-only token raises the API limit from
                   60 to 5,000 requests per hour. Unauthenticated is enough for
                   one run per hour.

No third-party packages. Python 3.8+.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
CHAINWEB = "kda-community/chainweb-node"
PACT5 = "kda-community/pact-5"
ORG = "kda-community"

BRANCHES = {
    "pact5_post_quantum": (PACT5, "post_quantum"),
    "chainweb_post_quantum_2": (CHAINWEB, "post_quantum_2"),
    "chainweb_pact5_migration": (CHAINWEB, "pact4_pact5_migration"),
}
PULLS = [43, 44, 45]
# Kadena mainnet node service API used to read the live fork number. First one that answers wins.
# Override with NODE_URL=http://host:1848 in the environment.
NODE_URLS = [u for u in [os.environ.get("NODE_URL")] if u] + [
    "http://193.122.85.1:1848",          # Kadena Nexus Saudi node
    "https://api.chainweb.com",          # legacy public endpoint, may be gone
]
POST_QUANTUM_FORK_NUMBER = 2             # Chainweb33 -> ForkAtForkNumber 2 in the draft Mainnet.hs
PQ_WORDS = ("post-quantum", "post quantum", "postquantum", "slh-dsa", "slh dsa", "q:", "chainweb 3.3",
            "chainweb33", "signature scheme", "pact4 / pact5", "pact4/pact5", "pact 5 migration", "pact5 migration")

_cache = {}


# ----------------------------------------------------------------------------
# HTTP helpers
# ----------------------------------------------------------------------------

def _request(url, accept="application/vnd.github+json"):
    if url in _cache:
        return _cache[url]
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "quantum-safe-kadena-status/2.0"})
    tok = os.environ.get("GITHUB_TOKEN")
    if tok and url.startswith(API):
        req.add_header("Authorization", "Bearer " + tok)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read()
                _cache[url] = body
                return body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                _cache[url] = None
                return None
            if e.code in (403, 429) and attempt < 2:
                time.sleep(15)
                continue
            raise
        except urllib.error.URLError:
            if attempt < 2:
                time.sleep(5)
                continue
            raise
    return None


def get(path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    body = _request(url)
    return json.loads(body) if body else None


def raw_file(repo, branch, path):
    body = _request(f"{RAW}/{repo}/{branch}/{path}", accept="text/plain")
    return body.decode("utf-8", "replace") if body else None


# ----------------------------------------------------------------------------
# Facts
# ----------------------------------------------------------------------------

def branch_info(repo, branch):
    b = get(f"/repos/{repo}/branches/{branch}")
    if not b:
        return None
    c = b["commit"]
    return {
        "sha": c["sha"][:8],
        "date": c["commit"]["committer"]["date"],
        "message": c["commit"]["message"].splitlines()[0][:120],
        "url": c["html_url"],
    }


def pull_info(repo, number):
    p = get(f"/repos/{repo}/pulls/{number}")
    if not p:
        return None
    return {
        "title": p["title"],
        "state": p["state"],
        # The Kadena devs often mark drafts in the title rather than with GitHub's draft flag.
        "draft": bool(p.get("draft")) or bool(re.search(r"\b(draft|wip)\b", p["title"], re.I)),
        "merged": p.get("merged_at") is not None,
        "updated_at": p["updated_at"],
        "url": p["html_url"],
    }


def latest_release(repo):
    r = get(f"/repos/{repo}/releases/latest")
    if not r:
        return None
    text = ((r.get("name") or "") + " " + (r.get("body") or "")).lower()
    return {
        "tag": r["tag_name"],
        "published_at": r.get("published_at"),
        "url": r["html_url"],
        "mentions_post_quantum": any(w in text for w in PQ_WORDS),
    }


def recent_items(repo, limit=8):
    items = get(f"/repos/{repo}/issues", {"state": "all", "sort": "updated", "per_page": 40}) or []
    out = []
    for it in items:
        text = (it["title"] + " " + (it.get("body") or "")).lower()
        if not any(w in text for w in PQ_WORDS):
            continue
        out.append({
            "number": it["number"],
            "title": it["title"],
            "type": "pr" if "pull_request" in it else "issue",
            "state": it["state"],
            "updated_at": it["updated_at"],
            "url": it["html_url"],
        })
        if len(out) >= limit:
            break
    return out


def branch_merged(repo, branch, base="master"):
    """True when every commit on `branch` is already in `base`."""
    c = get(f"/repos/{repo}/compare/{base}...{branch}")
    if not c:
        return False
    return c.get("status") in ("behind", "identical") or c.get("ahead_by") == 0


def version_tuple(tag):
    nums = re.findall(r"\d+", str(tag))
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def org_pr(repos_match, keywords, want_state):
    """Any PR in org repos whose name matches, with a keyword in the title, in the wanted state."""
    repos = get(f"/orgs/{ORG}/repos", {"per_page": 100, "type": "public"}) or []
    kws = [k.lower() for k in keywords]
    for r in repos:
        name = r["name"].lower()
        if not any(m.lower() in name for m in repos_match):
            continue
        pulls = get(f"/repos/{r['full_name']}/pulls", {"state": "all", "per_page": 50, "sort": "updated", "direction": "desc"}) or []
        for p in pulls:
            if not any(k in p["title"].lower() for k in kws):
                continue
            merged = p.get("merged_at") is not None
            if want_state == "merged" and merged:
                return p["html_url"]
            if want_state == "open" and p["state"] == "open":
                return p["html_url"]
    return None


def gas_prices():
    """Read the signature verification prices from InitialGasModel.hs, master first, then the draft branch."""
    for branch in ("master", "post_quantum_2"):
        txt = raw_file(CHAINWEB, branch, "src/Chainweb/Pact5/InitialGasModel.hs")
        if not txt:
            continue
        found = {}
        for key, name in (("ed25519", "ED25519"), ("webauthn", "WebAuthn"), ("slh_128s", "SlhDsaSha128s"),
                          ("slh_192s", "SlhDsaSha192s"), ("slh_256s", "SlhDsaSha256s")):
            # take the LAST match: the newest gas model is defined last in the file
            ms = re.findall(name + r"\s*->\s*([0-9]+(?:\.[0-9]+)?)", txt)
            if ms:
                found[key] = float(ms[-1])
        if "slh_128s" in found:
            found["source"] = branch
            return found
    return None


def mainnet_fork():
    """Fork number and vote count from the newest block on chain 0, via a node's service API."""
    for base in NODE_URLS:
        try:
            cut = json.loads(_request(base + "/chainweb/0.0/mainnet01/cut", accept="application/json"))
            h = cut["hashes"]["0"]
            hdr = json.loads(_request(base + "/chainweb/0.0/mainnet01/chain/0/header/" + h["hash"],
                                      accept="application/json;blockheader-encoding=object"))
            flags = int(hdr["featureFlags"])
            return {
                "node": base,
                "height": h["height"],
                "fork_number": flags & 0xFFFFFFFF,
                "fork_votes": flags >> 32,
                "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        except Exception as e:
            print(f"warn: node {base}: {e}", file=sys.stderr)
    return None


# ----------------------------------------------------------------------------
# Rule evaluation
# ----------------------------------------------------------------------------

def check(cond, S):
    """Evaluate one condition against the gathered facts. Returns (bool, note)."""
    if "all" in cond:
        notes = []
        for c in cond["all"]:
            ok, n = check(c, S)
            if not ok:
                return False, ""
            notes.append(n)
        return True, "; ".join(x for x in notes if x)
    if "any" in cond:
        for c in cond["any"]:
            ok, n = check(c, S)
            if ok:
                return True, n
        return False, ""

    if "pr_merged" in cond:
        p = S["pulls"].get(str(cond["pr_merged"])) or pull_info(CHAINWEB, cond["pr_merged"])
        return (bool(p and p["merged"]), f"PR #{cond['pr_merged']} merged")
    if "pr_open" in cond:
        p = S["pulls"].get(str(cond["pr_open"])) or pull_info(CHAINWEB, cond["pr_open"])
        return (bool(p and p["state"] == "open" and not p["draft"]), f"PR #{cond['pr_open']} open for review")
    if "branch_merged" in cond:
        repo, branch = cond["branch_merged"]
        return (branch_merged(repo, branch), f"{repo} {branch} merged into master")
    if "release_at_least" in cond:
        rel = S.get("latest_release") or {}
        ok = bool(rel.get("tag")) and version_tuple(rel["tag"]) >= version_tuple(cond["release_at_least"])
        return (ok, f"release {rel.get('tag')} published")
    if "file_lacks" in cond:
        repo, branch, path, text = cond["file_lacks"]
        content = raw_file(repo, branch, path)
        return (content is not None and text not in content, f"'{text}' no longer in {path} ({branch})")
    if "file_contains" in cond:
        repo, branch, path, text = cond["file_contains"]
        content = raw_file(repo, branch, path)
        return (content is not None and text in content, f"'{text}' present in {path} ({branch})")
    if "fork_number_at_least" in cond:
        f = S.get("mainnet_fork") or {}
        ok = f.get("fork_number") is not None and f["fork_number"] >= int(cond["fork_number_at_least"])
        return (ok, f"mainnet fork number {f.get('fork_number')} (block {f.get('height')})")
    if "fork_votes_started" in cond:
        f = S.get("mainnet_fork") or {}
        ok = f.get("fork_number") is not None and f["fork_number"] == int(cond["fork_votes_started"]) - 1 and f.get("fork_votes", 0) > 0
        return (ok, f"miners signaling for fork {cond['fork_votes_started']} ({f.get('fork_votes')} votes)")
    if "gas_on_master" in cond:
        g = S.get("gas") or {}
        return (g.get("source") == "master", "SLH-DSA gas prices present on master")
    if "org_pr" in cond:
        o = cond["org_pr"]
        url = org_pr(o["repos_match"], o["keywords"], o["state"])
        return (url is not None, f"{o['state']} PR in a client/wallet repo: {url}")
    return False, ""


def apply_rules(assessment, S):
    """Raise 'auto' per milestone when a rule is satisfied. Returns True if anything changed."""
    changed = False
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for m in assessment["milestones"]:
        best = float(m.get("auto") or 0)
        best_note = m.get("auto_evidence", "")
        for rule in m.get("rules", []):
            try:
                ok, note = check(rule["when"], S)
            except Exception as e:  # a failing lookup never lowers a score
                print(f"warn: rule on '{m['name']}': {e}", file=sys.stderr)
                continue
            if ok and float(rule["auto"]) > best:
                best, best_note = float(rule["auto"]), note
        if best > float(m.get("auto") or 0):
            m["auto"], m["auto_evidence"], m["auto_updated"] = best, best_note, today
            changed = True
            print(f"raised '{m['name']}' to {int(best*100)}%: {best_note}")
    if changed:
        assessment["auto_updated"] = today
    return changed


def effective_percent(assessment):
    import math
    return math.floor(1e-9 + sum(m["weight"] * max(float(m.get("done") or 0), float(m.get("auto") or 0)) for m in assessment["milestones"]))


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


# ----------------------------------------------------------------------------

def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    status_path = os.path.join(folder, "status.json")
    assess_path = os.path.join(folder, "assessment.json")

    S = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "pulls": {}}
    for key, (repo, branch) in BRANCHES.items():
        try:
            S[key] = branch_info(repo, branch)
        except Exception as e:
            S[key] = None
            print(f"warn: {key}: {e}", file=sys.stderr)
    for n in PULLS:
        try:
            info = pull_info(CHAINWEB, n)
            if info:
                S["pulls"][str(n)] = info
        except Exception as e:
            print(f"warn: pull {n}: {e}", file=sys.stderr)
    try:
        S["latest_release"] = latest_release(CHAINWEB)
    except Exception as e:
        S["latest_release"] = None
        print(f"warn: release: {e}", file=sys.stderr)
    try:
        S["recent_items"] = recent_items(CHAINWEB)
    except Exception as e:
        S["recent_items"] = []
        print(f"warn: recent items: {e}", file=sys.stderr)

    try:
        S["gas"] = gas_prices()
    except Exception as e:
        S["gas"] = None
        print(f"warn: gas: {e}", file=sys.stderr)
    S["mainnet_fork"] = mainnet_fork()

    write_json(status_path, S)
    print(f"wrote {status_path} at {S['generated_at']}")

    if os.path.exists(assess_path):
        with open(assess_path, encoding="utf-8") as f:
            A = json.load(f)
        if apply_rules(A, S):
            write_json(assess_path, A)
            print(f"wrote {assess_path}; effective progress now {effective_percent(A)}%")
        else:
            print(f"no milestone changes; effective progress {effective_percent(A)}%")


if __name__ == "__main__":
    main()
