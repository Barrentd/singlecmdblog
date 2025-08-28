#!/usr/bin/env python3
# TinyBlog Ultra (stdlib + optional python-markdown/pymdown-extensions)
# - Full Markdown when markdown/pymdownx present (fallback mini parser otherwise)
# - Ordered posts (new→old), consistent sticky navbar (Home/About + category select)
# - Day/Night theme toggle (persists via localStorage)
# - Menu toggle (hamburger) for small screens
# - In-memory dev server (--serve) and /assets/ static mapping
# - Enforces 14 KB/page size cap on written files

from __future__ import annotations
from pathlib import Path
import json, re, sys, argparse, html, time, datetime as dt, os, importlib.util, mimetypes, shutil
from http.server import BaseHTTPRequestHandler, HTTPServer

# ===================== CLI =====================
def parse_args():
    p = argparse.ArgumentParser(description="TinyBlog static generator")
    p.add_argument("--content", default="content", help="content directory (markdown)")
    p.add_argument("--public",  default="public",  help="static assets dir served at /assets/")
    p.add_argument("--out",     default="build",   help="output directory")
    p.add_argument("--site",    default="site.json", help="site config (title, palette, paletteDark)")
    p.add_argument("--base-url", default="/", help="base URL (e.g. / or /blog/)")
    p.add_argument("--max-bytes", type=int, default=14*1024, help="size budget per HTML file")
    p.add_argument("--serve", action="store_true", help="serve from memory (no files written)")
    p.add_argument("--host", default="127.0.0.1", help="dev server host")
    p.add_argument("--port", type=int, default=8080, help="dev server port")
    return p.parse_args()

# ===================== Markdown engines =====================
def _markdown_engine():
    if importlib.util.find_spec("markdown"):
        import markdown  # type: ignore
        exts = ["extra","sane_lists","smarty","toc","codehilite"]
        for name in ("pymdownx.tasklist","pymdownx.tilde","pymdownx.caret","pymdownx.emoji",
                     "pymdownx.superfences","pymdownx.highlight"):
            if importlib.util.find_spec(name): exts.append(name)
        md = markdown.Markdown(extensions=exts, extension_configs={
            "pymdownx.tasklist":{"custom_checkbox":True,"clickable_checkbox":False},
            "codehilite":{"guess_lang":False,"noclasses":False},
        })
        return lambda text: md.reset().convert(text)
    # fallback mini parser
    RX = [
        (re.compile(r"\*\*(.+?)\*\*"), r"<b>\1</b>"),
        (re.compile(r"\*(.+?)\*"), r"<i>\1</i>"),
        (re.compile(r"`(.+?)`"), lambda m: f"<code>{html.escape(m.group(1))}</code>"),
        (re.compile(r"!\[([^\]]*)\]\(([^)]+)\)"), r'<img alt="\1" src="\2">'),
        (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), r'<a href="\2">\1</a>'),
    ]
    def _mini(text:str)->str:
        lines=text.strip().splitlines(); out=[]; buf=[]
        def flush():
            if buf:
                t=" ".join(buf).strip()
                if t: out.append(f"<p>{t}</p>")
                buf.clear()
        for raw in lines:
            l=raw.rstrip()
            if not l: flush(); continue
            if l.startswith("# "): flush(); out.append(f"<h1>{html.escape(l[2:].strip())}</h1>"); continue
            if l.startswith("## "): flush(); out.append(f"<h2>{html.escape(l[3:].strip())}</h2>"); continue
            if l.strip()=="---": flush(); out.append("<hr>"); continue
            buf.append(html.escape(l))
        flush()
        s="".join(out)
        for rx,repl in RX: s=rx.sub(repl,s)
        return s
    return _mini

md_render=_markdown_engine()

# ===================== Front matter =====================
def parse_front_matter(md:str):
    if not md.startswith("---"): return {}, md
    end=md.find("\n---",3)
    if end==-1: return {}, md
    head=md[3:end].strip(); body=md[end+4:].lstrip("\n")
    meta={}
    for line in head.splitlines():
        if ":" in line:
            k,v=line.split(":",1)
            meta[k.strip().lower()]=v.strip()
    if "categories" in meta:
        meta["categories"]=[c.strip() for c in meta["categories"].split(",") if c.strip()]
    return meta, body

def parse_date(s:str)->dt.datetime|None:
    if not s: return None
    for fmt in ("%Y-%m-%d","%Y-%m-%d %H:%M","%Y-%m-%dT%H:%M","%Y-%m-%dT%H:%M:%S"):
        try: return dt.datetime.strptime(s,fmt)
        except ValueError: pass
    try: return dt.datetime.fromisoformat(s)
    except (ValueError, TypeError): return None

# ===================== Template / CSS / JS / minify =====================
BASE_CSS = (
":root{--bg:#f8f9fa;--fg:#2d3748;--muted:#718096;--link:#3182ce;--accent:#4299e1;--card:#f1f3f4;--card-border:#d1d5db}"
"@media(prefers-color-scheme:dark){:root{--bg:#0b0b0c;--fg:#eaeaea;--muted:#9aa0a6;--link:#8ab4f8;--accent:#60a5fa;--card:#0f172a;--card-border:#1f2937}}"
"/* explicit overrides when toggled */"
"html[data-theme=light]{--bg:#f8f9fa;--fg:#2d3748;--muted:#718096;--link:#3182ce;--accent:#4299e1;--card:#f1f3f4;--card-border:#d1d5db}"
"html[data-theme=dark]{--bg:#0b0b0c;--fg:#eaeaea;--muted:#9aa0a6;--link:#8ab4f8;--accent:#60a5fa;--card:#0f172a;--card-border:#1f2937}"
"*,*:before,*:after{box-sizing:border-box}"
"/* smooth theme transitions */"
"html{transition:background-color 0.3s ease,color 0.3s ease}"
"body,main,pre,code,.postcard,.navbar,.btn,.catselect,.chip{transition:background-color 0.3s ease,color 0.3s ease,border-color 0.3s ease}"
"html{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,'Helvetica Neue',Arial;font-size:16px;-webkit-text-size-adjust:100%}"
"body{margin:0;background:var(--bg);color:var(--fg);line-height:1.5}"
"main{max-width:min(92ch,96vw);margin:0 auto;padding:2.5vh 3vw}"
"h1{font-size:clamp(22px,4.5vw,30px);line-height:1.15;margin:10px 0 6px}"
"h2{font-size:clamp(18px,3.7vw,24px);line-height:1.2;margin:14px 0 8px}"
"p{margin:10px 0}a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}"
"code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}"
"/* Responsive code blocks with proper line handling */"
"pre{overflow-x:auto;overflow-y:hidden;padding:12px 16px;border:1px solid var(--card-border);border-radius:8px;background:var(--card);max-width:100%;white-space:pre;line-height:1.5;font-size:14px;tab-size:2}"
"pre code{padding:0;border:none;background:transparent;white-space:pre;display:block;overflow-wrap:normal;word-wrap:normal}"
"code{padding:2px 4px;border:1px solid var(--card-border);border-radius:4px;background:rgba(127,127,127,.08);font-size:0.9em;white-space:pre-wrap;word-wrap:break-word}"
"/* Better mobile handling for code blocks */"
"@media(max-width:768px){pre{font-size:13px;padding:10px 12px;margin:8px -3vw;border-radius:0;border-left:none;border-right:none;line-height:1.4}code{font-size:0.85em}}"
"@media(max-width:480px){pre{font-size:12px;padding:8px 10px;line-height:1.3}}"
"img{max-width:100%;height:auto;border-radius:6px}"
"table{width:100%;border-collapse:collapse;display:block;overflow-x:auto}"
"th,td{border:1px solid var(--card-border);padding:.4rem .5rem;text-align:left;vertical-align:top}"
"blockquote{border-left:3px solid var(--card-border);margin:.8rem 0;padding:.1rem .8rem;color:var(--muted)}"
"ul,ol{margin:.4rem 0 .6rem .9rem}.task-list-item{list-style:none}.task-list-item input{margin-right:.5rem}"
"hr{border:0;border-top:1px solid var(--card-border);margin:12px 0}footer{margin-top:16px;font-size:.85rem;opacity:.7}"
"/* chips for categories */"
".chip{display:inline-block;padding:2px 6px;border:1px solid var(--card-border);border-radius:999px;background:var(--card);color:var(--fg)}"
"/* navbar + toggles */"
".navbar{position:sticky;top:0;z-index:10;background:var(--bg);border-bottom:1px solid var(--card-border);backdrop-filter:saturate(180%) blur(6px)}"
".navwrap{max-width:min(92ch,96vw);margin:0 auto;padding:.55rem 3vw;display:flex;gap:10px;align-items:center}"
".brand{font-weight:700}.navlink{margin-right:10px}.spacer{flex:1}"
".btn{font:inherit;padding:.35rem .55rem;border:1px solid var(--card-border);border-radius:8px;background:var(--card);color:var(--fg);cursor:pointer}"
".menu-panel{display:flex;gap:10px;align-items:center;flex-wrap:wrap}"
".catselect{font:inherit;padding:.35rem .5rem;border:1px solid var(--card-border);border-radius:8px;background:var(--card);color:var(--fg)}"
"#menuToggle{display:none}"
"@media(max-width:700px){.menu-panel{display:none}html.menu-open .menu-panel{display:flex}#menuToggle{display:inline-block}}"
"/* ordered list with clickable cards and thumbnails */"
".postlist{list-style:none;margin:0;padding:0}"
".postcard{margin:.45rem 0;border-radius:8px;background:var(--card);border:1px solid var(--card-border);display:block;text-decoration:none;color:inherit;position:relative}"
".postcard{transition:box-shadow .2s ease,transform .2s ease,background-color 0.3s ease,border-color 0.3s ease}"
".postcard:hover{box-shadow:0 4px 12px rgba(0,0,0,.1);text-decoration:none;transform:translateY(-1px)}"
"@media(prefers-color-scheme:dark){.postcard:hover{box-shadow:0 4px 12px rgba(255,255,255,.1)}}"
"html[data-theme=dark] .postcard:hover{box-shadow:0 4px 12px rgba(255,255,255,.1)}"
".postcontent{display:flex;gap:14px;padding:.7rem;min-height:100px}"
".postthumbnail{flex-shrink:0;width:140px;height:90px;border-radius:8px;overflow:hidden;background:var(--card-border);display:flex;align-items:center;justify-content:center}"
".postthumbnail img{width:100%;height:100%;object-fit:cover}"
".postthumbnail-placeholder{color:var(--muted);font-size:32px}"
".postinfo{flex:1;display:flex;flex-direction:column;justify-content:space-between;min-height:90px}"
".posttitle{font-weight:600;margin:0 0 8px;line-height:1.3}"
".postsubtitle{font-weight:400;font-size:.9rem;color:var(--muted);margin:0 0 8px;line-height:1.3}"
".postmeta{display:flex;gap:8px;align-items:center;color:var(--muted);font-size:.85rem;margin-top:8px;flex-wrap:wrap}"
"/* responsive adjustments */"
"@media(max-width:600px){.postcontent{flex-direction:column;gap:10px}.postthumbnail{width:100%;height:120px;margin-top:8px}.postinfo{min-height:auto}}"
"/* disable transitions for users who prefer reduced motion */"
"@media(prefers-reduced-motion:reduce){html,body,main,pre,code,.postcard,.navbar,.btn,.catselect,.chip{transition:none!important}}"
"meta,link,script,style{display:none}"
)

def palette_override(light:dict|None, dark:dict|None)->str:
    def css_from(prefix:str, pal:dict):
        return (f"{prefix}{{--bg:{pal.get('bg','#fff')};--fg:{pal.get('fg','#111')};--muted:{pal.get('muted','#666')};"
                f"--link:{pal.get('link','#0a6cff')};--accent:{pal.get('accent','#3b82f6')};"
                f"--card:{pal.get('card','#f8fafc')};--card-border:{pal.get('cardBorder','#e5e7eb')}}}")
    css=""
    if light: css+=css_from("html[data-theme=light]", light)
    if dark:  css+=css_from("html[data-theme=dark]",  dark)
    return css

NAV_JS = (
"(function(){const d=document,rt=d.documentElement;const KEY='tb-theme';"
"function apply(t){rt.dataset.theme=t;try{localStorage.setItem(KEY,t)}catch(e){}}"
"function initTheme(){let t=(()=>{try{return localStorage.getItem(KEY)}catch(e){return null}})();"
"if(!t){t=matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light'}apply(t);"
"var b=d.getElementById('themeToggle');if(b){b.textContent=(rt.dataset.theme==='dark'?'☀️':'🌙');"
"b.onclick=function(){var v=(rt.dataset.theme==='dark'?'light':'dark');apply(v);b.textContent=(v==='dark'?'☀️':'🌙');}}}"
"function initMenu(){var m=d.getElementById('menuToggle');if(m){m.onclick=function(){rt.classList.toggle('menu-open');}}"
"var sel=d.getElementById('categorySelect');if(sel){sel.onchange=function(){if(sel.value)location.href=sel.value;}}}"
"if(d.readyState==='loading'){d.addEventListener('DOMContentLoaded',function(){initTheme();initMenu();});}"
"else{initTheme();initMenu();}})();"
)

def build_nav(site_title:str, base_url:str, categories_sorted:list[tuple[str,str]], pages:dict)->str:
    # Construire les liens de navigation pour toutes les pages
    nav_links = [f'<a class="navlink" href="{base_url}index.html">Home</a>']
    
    # Ajouter toutes les pages au menu (triées par titre)
    for slug, page_data in sorted(pages.items(), key=lambda x: x[1]["title"]):
        nav_links.append(f'<a class="navlink" href="{base_url}{slug}.html">{html.escape(page_data["title"])}</a>')
    
    links = "".join(nav_links)
    
    if categories_sorted:
        opts="".join(f'<option value="{base_url}category/{s}.html">{html.escape(n)}</option>' for n,s in categories_sorted)
        select=(f'<select id="categorySelect" class="catselect" aria-label="Categories">'
                f'<option value="">{html.escape("Categories")}</option>'
                f'<option value="{base_url}index.html">All</option>{opts}</select>')
    else:
        select=""
    return ('<div class="navbar"><div class="navwrap">'
            f'<a class="brand navlink" href="{base_url}index.html">{html.escape(site_title)}</a>'
            '<span class="spacer"></span>'
            '<button id="menuToggle" class="btn" aria-label="Menu" title="Menu">☰</button>'
            '<button id="themeToggle" class="btn" aria-label="Toggle theme" title="Toggle theme">🌙</button>'
            f'</div><div class="navwrap menu-panel">{links}{select}</div></div>')

def render_page(doc_title:str, body_html:str, site_title:str, base_url:str, palette_css:str, nav_html:str)->str:
    return ("<!doctype html><meta charset=utf-8>"
            f"<title>{html.escape(doc_title)}</title>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<meta name=generator content=TinyBlog>"
            f"<style>{BASE_CSS}{palette_css}</style>"
            f"{nav_html}<main><header><h1>{html.escape(doc_title)}</h1></header>"
            f"{body_html}<footer></footer></main>"
            f"<script>{NAV_JS}</script>")

def minify_html(s:str)->str:
    s=re.sub(r">\s+<","><",s); s=re.sub(r"\s{2,}"," ",s); return s.strip()

# ===================== Helpers =====================
def read_site(site_path:Path)->dict:
    return json.loads(site_path.read_text(encoding="utf-8")) if site_path.exists() else {"title":"TinyBlog","description":""}

def slugify(s:str)->str:
    s=s.lower(); s=re.sub(r"[^a-z0-9]+","-",s).strip("-"); return re.sub(r"-{2,}","-",s) or "uncategorized"

def excerpt_from_md(md:str, limit:int=160)->str:
    for line in md.splitlines():
        t=line.strip()
        if not t or t.startswith("#"): continue
        txt=re.sub(r"`(.+?)`",r"\1",t)
        return (txt[:limit]+"…") if len(txt)>limit else txt
    return ""

def collect_entries(content_dir:Path):
    posts, pages = [], {}
    for f in sorted(content_dir.glob("*.md")):
        raw=f.read_text(encoding="utf-8").strip()
        meta, body = parse_front_matter(raw)
        title = meta.get("title") or (body.splitlines()[0].lstrip("# ").strip() if body else f.stem) or f.stem
        subtitle = meta.get("subtitle", "")
        page_kind=(meta.get("page") or "").lower()
        # Modifié : accepter toute valeur truthy pour "page"
        is_page = page_kind in ("about","page","true") or str(meta.get("page","")).lower() in ("true","1","yes") or f.stem.lower()=="about"
        date_obj = parse_date(meta.get("date","")) or dt.datetime.fromtimestamp(f.stat().st_mtime)
        date_str = date_obj.strftime("%Y-%m-%d")
        cats = meta.get("categories") or []
        thumbnail = meta.get("thumbnail", "")
        entry = {"slug":f.stem,"title":title,"subtitle":subtitle,"md":body,
                 "categories":cats,"categories_slug":[slugify(c) for c in cats],
                 "excerpt":excerpt_from_md(body),"date_obj":date_obj,"date_str":date_str,
                 "thumbnail":thumbnail}
        if is_page:
            pages[f.stem.lower()] = entry
        else:
            posts.append(entry)
    return posts, pages

def build_ordered_list(items, base_url:str)->str:
    cards=[]
    for p in items:
        # Thumbnail
        if p.get("thumbnail"):
            thumb_html = f'<div class="postthumbnail"><img src="{html.escape(p["thumbnail"])}" alt="Thumbnail for {html.escape(p["title"])}" loading="lazy"></div>'
        else:
            thumb_html = '<div class="postthumbnail"><div class="postthumbnail-placeholder">📄</div></div>'
        
        # Categories chips
        chips = " ".join(f'<span class="chip">{html.escape(n)}</span>'
                        for n in p["categories"])
        
        # Meta info
        meta_parts = [f'<span>{p["date_str"]}</span>']
        if chips:
            meta_parts.append(chips)
        meta_html = f'<div class="postmeta">{"".join(meta_parts)}</div>'
        
        # Title with optional subtitle
        title_html = f'<h3 class="posttitle">{html.escape(p["title"])}</h3>'
        if p.get("subtitle"):
            title_html += f'<h4 class="postsubtitle">{html.escape(p["subtitle"])}</h4>'
        
        # Post info (sans excerpt)
        post_info = (f'<div class="postinfo">'
                    f'{title_html}'
                    f'{meta_html}'
                    f'</div>')
        
        # Complete card
        card = (f'<li><a class="postcard" href="{base_url}{p["slug"]}.html">'
               f'<div class="postcontent">{post_info}{thumb_html}</div>'
               f'</a></li>')
        cards.append(card)
    
    return '<ol class="postlist">'+"".join(cards)+"</ol>"

def bytes_ok(path:Path, limit:int):
    size=path.stat().st_size
    if size>limit: raise SystemExit(f"[FAIL] {path.name} = {size} bytes > {limit}")
    print(f"[OK]   {path.name} = {size} bytes")

# ===================== In-memory server =====================
class _MemHandler(BaseHTTPRequestHandler):
    pages:dict[str,str]={}
    public_dir:Path|None=None
    def do_GET(self):
        route=self.path
        if route=="/" or route.endswith("/"): route="/index.html"
        if route.startswith("//"): route=route[1:]
        page=self.pages.get(route)
        if page is not None:
            self.send_response(200); self.send_header("content-type","text/html; charset=utf-8")
            self.send_header("cache-control","no-store, max-age=0"); self.end_headers()
            self.wfile.write(page.encode("utf-8")); return
        if route.startswith("/assets/") and self.public_dir:
            fs=(self.public_dir/route[len("/assets/"):]).resolve()
            if fs.is_file() and str(fs).startswith(str(self.public_dir.resolve())):
                ctype=mimetypes.guess_type(str(fs))[0] or "application/octet-stream"
                self.send_response(200); self.send_header("content-type",ctype)
                self.send_header("cache-control","no-store, max-age=0"); self.end_headers()
                with fs.open("rb") as f: shutil.copyfileobj(f,self.wfile); return
        self.send_response(404); self.send_header("content-type","text/plain; charset=utf-8")
        self.end_headers(); self.wfile.write(b"404")

# ===================== Build =====================
def build(args):
    root=Path.cwd()
    content_dir=root/args.content
    public_dir=root/args.public
    out_dir=root/args.out
    site=read_site(root/args.site)

    pal_css=palette_override(site.get("palette"), site.get("paletteDark"))

    posts, pages = collect_entries(content_dir)
    posts.sort(key=lambda p:p["date_obj"], reverse=True)

    # categories
    cat_map={}
    for p in posts:
        if not p["categories"]:
            cat_map.setdefault("uncategorized",("Uncategorized",[]))[1].append(p)
        else:
            for name,slug in zip(p["categories"],p["categories_slug"]):
                cat_map.setdefault(slug,(name,[]))[1].append(p)
    categories_sorted=sorted([(v[0],k) for k,v in cat_map.items()], key=lambda x:x[0].lower())

    # Modifié : passer les pages au lieu de has_about
    nav_html=build_nav(site.get("title","TinyBlog"), args.base_url, categories_sorted, pages)

    rendered={}

    # index
    idx_body=build_ordered_list(posts, args.base_url)
    rendered["/index.html"]=minify_html(render_page("Home", idx_body, site.get("title","TinyBlog"), args.base_url, pal_css, nav_html))

    # Modifié : générer toutes les pages au lieu de seulement "about"
    for slug, page_data in pages.items():
        rendered[f"/{slug}.html"]=minify_html(render_page(page_data["title"], md_render(page_data["md"]), site.get("title","TinyBlog"), args.base_url, pal_css, nav_html))

    # posts
    for p in posts:
        chips=" ".join(f'<a class="chip" href="{args.base_url}category/{s}.html">{html.escape(n)}</a>'
                       for n,s in zip(p["categories"],p["categories_slug"]))
        head=f'<div class="postmeta"><span>{p["date_str"]}</span>{chips}</div>'
        body_html=head+md_render(p["md"])
        rendered[f"/{p['slug']}.html"]=minify_html(render_page(p["title"], body_html, site.get("title","TinyBlog"), args.base_url, pal_css, nav_html))

    # categories
    for slug,(name,plist) in cat_map.items():
        plist_sorted=sorted(plist,key=lambda p:p["date_obj"],reverse=True)
        body=build_ordered_list(plist_sorted, args.base_url)
        rendered[f"/category/{slug}.html"]=minify_html(render_page(f"Category · {name}", body, site.get("title","TinyBlog"), args.base_url, pal_css, nav_html))

    if args.serve:
        _MemHandler.pages=rendered
        _MemHandler.public_dir=public_dir if public_dir.exists() else None
        srv=HTTPServer((args.host,args.port),_MemHandler)
        print(f"[SERVE] http://{args.host}:{args.port}  (HTML from memory; static from {public_dir}/ at /assets/)")
        try: srv.serve_forever()
        except KeyboardInterrupt: print("\n[STOP] server stopped"); srv.server_close()
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    for route, html_doc in rendered.items():
        out_file=out_dir/route.lstrip("/")
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(html_doc, encoding="utf-8")
        bytes_ok(out_file, args.max_bytes)
    if public_dir.exists():
        for src in public_dir.rglob("*"):
            if src.is_file():
                rel=src.relative_to(public_dir)
                dst=out_dir/"assets"/rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src,dst)
    print(f"[DONE] {len(posts)} post(s), {len(cat_map)} category page(s) + index @ {time.strftime('%Y-%m-%d %H:%M:%S')}")

if __name__=="__main__":
    build(parse_args())
