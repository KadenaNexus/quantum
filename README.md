# Quantum-Safe Kadena

How Kadena's post-quantum accounts will work, with a progress bar toward production that updates itself from the core developers' public work.

Part of [Kadena Nexus](https://kadena.ws). Live at https://quantum.kadena.ws

**Status:** live. The source deployed on the server is being committed here (issue #1); this README is the placeholder until then.

## Team

Built by the Kadena Nexus dev team (lead: Mustafa Zahid). Project lead: Saudi.KDA.

## Rules for this repo

No keys or `.env` files in git. Commit to `main` through pull requests; tag every deployment.

## Bringing existing code in

This repository starts with this README only. To add code that already has its own history, merge it in rather than force-pushing:

```
git remote add nexus https://github.com/KadenaNexus/quantum.git
git fetch nexus
git merge nexus/main --allow-unrelated-histories   # keeps both histories; resolve README.md if both have one
git push nexus HEAD:main
```
