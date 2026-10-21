"""Opt-in deploy of a generated demo. ADDITIVE ONLY: copies work/<slug>/site into vflights/public/v2/<slug>/ and
prints (does not run) the remaining steps, because the Vercel deploy ships the whole live-demos-sa site.
Never touches public/index.html, other demos, embed/*, or other agents.
  python deploy.py <slug>
"""
import os, shutil, sys
HERE = os.path.dirname(os.path.abspath(__file__))
S = "/private/tmp/claude-501/-Users-nabilrehman-Downloads-livekit-demo-agent/3cb0ded0-74a9-4dff-b0b7-bb53c4643301/scratchpad"
slug = sys.argv[1]
dst = os.path.join(S, "vflights", "public", "v2", slug)
if os.path.exists(dst):
    shutil.rmtree(dst)
shutil.copytree(os.path.join(HERE, "work", slug, "site"), dst)
print(f"copied -> {dst}")
print(f"""Remaining (run by hand, after checking nobody else is mid-edit in vflights):
 1. agent: worktree of generator-v2, Dockerfile = windcreek.Dockerfile, knowledge copied to knowledge/{slug}/,
    secrets AGENT_NAME=live-demo-{slug}-grok BRAIN=grok MIN_RT_VOICE=eve SITE_KNOWLEDGE=/app/knowledge/{slug}
    lk agent create --project nabil-demo --region us-east --secrets-file <file> --silent .
 2. api/token.js AGENTS: add  '{slug}-grok': 'live-demo-{slug}-grok',
 3. cd {S}/vflights && npx vercel deploy --prod --yes --force --scope livekit-b9da233b
 URL: https://live-demos-sa.vercel.app/v2/{slug}/?code=<code>""")
