"""One-time HTTPS credential handoff to the host bridge, never to an AI runner."""
import hmac
import os
import time
import urllib.request
from pathlib import Path
from fastapi import APIRouter,HTTPException,Form
from fastapi.responses import HTMLResponse
from services.resource_bank.tasks import root,REPO
router=APIRouter(prefix='/resource-bank',tags=['resource bank setup'])

def verify(key):
    path=root()/'.setup-key'
    if not path.exists() or time.time()-path.stat().st_mtime>1800 or not hmac.compare_digest(path.read_text().strip(),key):raise HTTPException(404,'Setup session not found')
    return path

@router.get('/setup/{key}',response_class=HTMLResponse)
def form(key:str):
    verify(key)
    return HTMLResponse('''<!doctype html><html><meta name="viewport" content="width=device-width"><title>SomaLoom GitHub connection</title><body style="font-family:system-ui;max-width:650px;margin:60px auto;padding:20px"><h1>Connect the resource bank</h1><p>Connect only kawalyauma/SomaLoom with Contents and Issues read/write access. The token stays on this server and is never shared with an AI runner or committed to GitHub.</p><form method="post"><label>Repository connection token<input type="password" name="token" required autocomplete="off" style="display:block;width:95%;padding:12px;margin:16px 0"></label><button style="padding:12px">Connect resource bank</button></form></body></html>''',headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"})

@router.post('/setup/{key}',response_class=HTMLResponse)
def connect(key:str,token:str=Form(...,min_length=20,max_length=512)):
    path=verify(key)
    if not token.startswith(('github_pat_','ghp_')):raise HTTPException(422,'Use the repository-scoped GitHub token')
    req=urllib.request.Request('https://api.github.com/repos/'+REPO,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'SomaLoom-Resource-Bank'})
    try:
        with urllib.request.urlopen(req,timeout=20) as response:
            if response.status!=200:raise ValueError()
    except Exception:raise HTTPException(422,'GitHub did not accept this repository connection') from None
    target=root()/'.github-token';temp=root()/'.github-token.tmp'
    with temp.open('w') as stream:os.chmod(temp,0o600);stream.write(token)
    os.replace(temp,target);path.unlink()
    return HTMLResponse('<title>Resource bank connected</title><h1>Resource bank connected</h1><p>The server can now commit references and create issues in SomaLoom.</p>',headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
