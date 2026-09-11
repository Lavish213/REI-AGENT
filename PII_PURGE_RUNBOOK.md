# PropWire PII Purge — Runbook

**Status: half done. The second half needs a human decision and cannot be
automated from here.**

## What was in the repository

Two files, 578 data rows of real personal information:

```
scripts/data/propwire_distressed.csv    182 rows
scripts/data/propwire_export.csv        398 rows
```

Columns included `Owner 1–4 First Name` / `Last Name`, `Owner Mailing Address`,
`City`, `State`, `Zip`, and `Listing Agent Full Name` / `Email` / `Phone`.

Named individuals, their home addresses, and named real-estate agents with
direct contact details.

## What has been done

- Both files removed from the working tree and from the index.
- `.gitignore` now excludes `scripts/data/*.csv`.
- Verified no code breaks: `scripts/seed_propwire.py` reads whatever file is at
  that path, and `backend/scout/cron.py` already instructs the operator to
  "drop a Propwire export into scripts/data/". The committed samples were never
  required — the operator supplies the file.

## What has NOT been done, and why

**The data is still in Git history.** Every commit that ever contained these
files still contains them. `git log -- scripts/data/` will find them, and so
will anyone with a clone or fork.

History rewriting is destructive and coordinated. It invalidates every existing
clone, breaks open pull requests, and changes every commit SHA after the
earliest affected commit. It is not something to run unannounced, so it is
written down here rather than executed.

## The purge

**1 — Inventory first.**

```bash
git log --oneline --all -- scripts/data/
git rev-list --objects --all | grep propwire
```

Record which branches and tags are affected.

**2 — Tell everyone with a clone to stop pushing.** Anyone who pushes an old
branch afterwards reintroduces the data.

**3 — Rewrite.** `git-filter-repo` is the supported tool; `filter-branch` is
deprecated and slower.

```bash
pip install git-filter-repo
git clone --mirror https://github.com/Lavish213/REI-AGENT.git rei-mirror
cd rei-mirror
git filter-repo --path scripts/data/propwire_distressed.csv \
                --path scripts/data/propwire_export.csv \
                --invert-paths
```

**4 — Verify before pushing.**

```bash
git rev-list --objects --all | grep propwire        # expect no output
```

**5 — Force-push all refs**, then have every collaborator delete their clone and
re-clone. Rebasing an old clone onto the rewritten history reintroduces the
blobs.

**6 — Ask GitHub Support to purge cached views.** Rewriting history does not
remove cached blob views or forks. GitHub documents this explicitly and will
clear them on request — the rewrite is not complete until they have.

**7 — Rotate anything that leaked.** No API keys were found in these files, but
run a full-history secret scan while the mirror is local.

## The question this raises

These rows describe identifiable people who did not consent to appear in a
source-control system. Whether their presence in a private repository — and in
whatever forks and clones exist — triggers a notification obligation under
CCPA/CPRA is a question for counsel, not for this document.

Add it to the same consultation as the TCPA questions in `AUDIT_AND_GRADE.md`
§2. It costs nothing extra to ask while you are already on the phone.

## Prevention

`.gitignore` now blocks `scripts/data/*.csv`. That is necessary and not
sufficient — `git add -f` overrides it. A pre-commit hook that rejects files
matching personal-data column headers is the durable fix, and belongs with the
CI work in Gate 3.
