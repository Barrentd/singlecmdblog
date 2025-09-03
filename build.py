#!/usr/bin/env python3
# TinyBlog Ultra (stdlib + optional python-markdown/pymdown-extensions)
# - Full Markdown when markdown/pymdownx present (fallback mini parser otherwise)
# - Ordered posts (new→old), consistent sticky navbar (Home/About + category select)
# - Day/Night theme toggle (persists via localStorage)
# - Menu toggle (hamburger) for small screens
# - In-memory dev server (--serve) and /assets/ static mapping
# - Enforces 14 KB/page size cap on written files

from __future__ import annotations

import argparse
import datetime as dt
import html
import importlib.util
import json
import mimetypes
import re
import shutil
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

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
    # Nouveau: URL vers le CSS de thème (servi depuis /assets/)
    p.add_argument("--theme-css", default="assets/css/theme.css", help="URL du fichier CSS de thème (servi via /assets)")
    return p.parse_args()

# ===================== Markdown engines =====================
def _markdown_engine():
    if importlib.util.find_spec("markdown"):
        import markdown  # type: ignore

        # Pas de codehilite/pymdownx.highlight -> laisser HLJS faire la coloration
        exts = ["extra","sane_lists","smarty","toc"]
        for name in ("pymdownx.tasklist","pymdownx.tilde","pymdownx.caret","pymdownx.emoji",
                     "pymdownx.superfences"):
            if importlib.util.find_spec(name): exts.append(name)
        md = markdown.Markdown(extensions=exts, extension_configs={
            "pymdownx.tasklist":{"custom_checkbox":True,"clickable_checkbox":False},
        })
        return lambda text: md.reset().convert(text)

    # fallback mini parser: titres, hr, paragraphes, inline, fenced code ```
    def _mini(text:str)->str:
        lines=text.splitlines()
        out:list[str]=[]
        buf:list[str]=[]
        in_code=False
        code_lang=""
        code_buf:list[str]=[]

        def flush_p():
            nonlocal buf
            if not buf: return
            t=" ".join(buf).strip()
            if t:
                # t est déjà échappé (voir plus bas)
                t=re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
                t=re.sub(r"\*(.+?)\*", r"<i>\1</i>", t)
                # ne pas ré-échapper à l'intérieur
                t=re.sub(r"`(.+?)`", r"<code>\1</code>", t)
                t=re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2">', t)
                t=re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
                out.append(f"<p>{t}</p>")
            buf=[]

        for raw in lines:
            l=raw.rstrip("\n")
            ls=l.strip()

            if in_code:
                if ls.startswith("```"):
                    code_html=html.escape("\n".join(code_buf))
                    cls=f' class="language-{code_lang}"' if code_lang else ""
                    out.append(f"<pre><code{cls}>{code_html}</code></pre>")
                    in_code=False; code_lang=""; code_buf=[]
                else:
                    code_buf.append(l)
                continue

            if ls.startswith("```"):
                flush_p()
                code_lang=ls[3:].strip().lower()
                in_code=True; code_buf=[]
                continue

            if not ls:
                flush_p(); continue

            if l.startswith("# "):
                flush_p(); out.append(f"<h1>{html.escape(l[2:].strip())}</h1>"); continue
            if l.startswith("## "):
                flush_p(); out.append(f"<h2>{html.escape(l[3:].strip())}</h2>"); continue
            if ls=="---":
                flush_p(); out.append("<hr>"); continue

            # stocker déjà échappé pour éviter toute injection
            buf.append(html.escape(l))

        flush_p()
        if in_code:
            code_html=html.escape("\n".join(code_buf))
            cls=f' class="language-{code_lang}"' if code_lang else ""
            out.append(f"<pre><code{cls}>{code_html}</code></pre>")
        return "".join(out)

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
"/* ...existing css jusqu'à la ligne social... */"
"/* Presentation section intégrée dans le header */"
".header-content{text-align:center;display:flex;flex-direction:column;align-items:center;gap:1rem}"
".presentation{text-align:center;margin:0;padding:0;border:none;display:flex;flex-direction:column;align-content:center;justify-content:center;align-items:center}"
".presentation-photo{width:120px;height:120px;border-radius:50%;object-fit:cover;margin:0;display:block;border:3px solid var(--card-border)}"
".presentation-title{font-size:clamp(18px,3.5vw,24px);font-weight:500;margin:0;color:var(--muted);order:2}"
".presentation-text{font-size:1rem;line-height:1.5;color:var(--muted);max-width:500px;margin:0;order:3}"
"header h1{order:1;margin:0}"
"@media(max-width:600px){.presentation-photo{width:100px;height:100px}.presentation-text{font-size:0.9rem;max-width:100%}.presentation-title{font-size:clamp(16px,3vw,20px)}}"
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

# Early theme boot to avoid initial fade (set theme + charger thème HLJS sans flash)
THEME_BOOT_JS = (
"(function(){var d=document,rt=d.documentElement;"
"rt.setAttribute('data-tb-init','1');"
"var t=null;try{t=localStorage.getItem('tb-theme')}catch(e){}"
"if(!t){t=matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light'}"
"rt.dataset.theme=t;"
"var ln=d.createElement('link');ln.id='hljs-theme';ln.rel='stylesheet';"
"ln.href=(t==='dark'"
"? 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.1/styles/github-dark.min.css'"
": 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.1/styles/github.min.css');"
"d.head.appendChild(ln);"
"})();"
)

# Updated nav/menu/theme script (toggle + switch de thème HLJS + GitLab-like code blocks)
NAV_JS = (
"(function(){const d=document,rt=d.documentElement;const KEY='tb-theme';"
"function setHLJSTheme(t){var ln=d.getElementById('hljs-theme');"
"if(!ln){ln=d.createElement('link');ln.id='hljs-theme';ln.rel='stylesheet';d.head.appendChild(ln);} "
"ln.href=(t==='dark'"
"? 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.1/styles/github-dark.min.css'"
": 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.1/styles/github.min.css');}"
"function apply(t){rt.dataset.theme=t;setHLJSTheme(t);try{localStorage.setItem(KEY,t)}catch(e){}}"
"function initUI(){"
" setHLJSTheme(rt.dataset.theme||'light');"
" var b=d.getElementById('themeToggle');if(b){b.textContent=(rt.dataset.theme==='dark'?'☀️':'🌙');"
" b.onclick=function(){var v=(rt.dataset.theme==='dark'?'light':'dark');apply(v);b.textContent=(v==='dark'?'☀️':'🌙');}}"
" var m=d.getElementById('menuToggle');if(m){m.onclick=function(){rt.classList.toggle('menu-open');}}"
" var sel=d.getElementById('categorySelect');if(sel){sel.onchange=function(){if(sel.value)location.href=sel.value;}}"
" requestAnimationFrame(function(){rt.removeAttribute('data-tb-init');});"
"}"
"if(d.readyState==='loading'){d.addEventListener('DOMContentLoaded',initUI);}else{initUI();}"
"})();"
)

HLJS_JS = (
"(function(){const d=document;"
"function enhanceCode(){"
" var idx=1;"
" d.querySelectorAll('pre>code').forEach(function(code){"
"   var pre=code.parentElement;if(pre.dataset.glified==='1')return;pre.dataset.glified='1';"
"   var lang='';code.classList.forEach(function(c){if(c.indexOf('language-')===0){lang=c.slice(9);}});"
"   if(!lang){lang=(code.getAttribute('data-lang')||'').toLowerCase();}"
"   pre.setAttribute('data-canonical-lang',lang||'');"
"   pre.classList.add('code','highlight','js-syntax-highlight');"
"   if(lang){pre.classList.add('language-'+lang);}"
"   if(!pre.id){pre.id='code-'+(idx++);}"
"   var raw=(code.textContent||'').replace(/\\r\\n?/g,'\\n');"
"   function esc(s){return s.replace(/[&<>]/g,function(ch){return ch==='&'?'&amp;':(ch==='<'?'&lt;':'&gt;')});}"
"   var html=esc(raw);"
"   if(window.hljs){"
"     try{"
"       if(lang && hljs.getLanguage && hljs.getLanguage(lang)){"
"         html=hljs.highlight(raw,{language:lang}).value;"
"       }else if(hljs.highlightAuto){"
"         var r=hljs.highlightAuto(raw);html=r.value;}"
"     }catch(e){}"
"   }"
"   var parts=html.split('\\n');"
"   for(var i=0;i<parts.length;i++){"
"     parts[i]='<span lang=\"'+(lang||'plaintext')+'\" class=\"line\" id=\"LC'+(i+1)+'\">'+parts[i]+'</span>';"
"   }"
"   code.innerHTML=parts.join('\\n');"
"   var wrap=d.createElement('div');wrap.className='gl-relative markdown-code-block js-markdown-code';"
"   pre.parentNode.insertBefore(wrap,pre);wrap.appendChild(pre);"
"   var cpy=d.createElement('copy-code');"
"   var btn=d.createElement('button');btn.type='button';btn.className='btn btn-sm';"
"   btn.setAttribute('aria-label','Copy to clipboard');btn.title='Copy to clipboard';btn.textContent='Copy';"
"   btn.addEventListener('click',function(){"
"     var txt=raw;"
"     if(navigator.clipboard&&navigator.clipboard.writeText){"
"       navigator.clipboard.writeText(txt).then(function(){btn.textContent='Copied';setTimeout(function(){btn.textContent='Copy';},1200);});"
"     }else{"
"       var ta=d.createElement('textarea');ta.value=txt;d.body.appendChild(ta);ta.select();try{d.execCommand('copy');}finally{d.body.removeChild(ta);}btn.textContent='Copied';setTimeout(function(){btn.textContent='Copy';},1200);"
"     }"
"   });"
"   cpy.appendChild(btn);wrap.appendChild(cpy);"
" });"
"}"
"if(d.readyState==='loading'){d.addEventListener('DOMContentLoaded',enhanceCode);}else{enhanceCode();}"
"})();"
)

def build_nav(site_title:str, base_url:str, categories_sorted:list[tuple[str,str]], pages:dict, social_links_html:str="")->str:
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
            '</div><div class="navwrap menu-panel">'
            f'{links}{select}{social_links_html}'
            '</div></div>')

def build_presentation_section(presentation_config: dict, base_url: str) -> str:
    """Génère la section de présentation pour intégration dans le header"""
    if not presentation_config or not presentation_config.get("enabled", False):
        return ""
    
    title = presentation_config.get("title", "")
    text = presentation_config.get("text", "")
    photo_url = make_asset_url(presentation_config.get("photo"), base_url)
    
    if not title and not text and not photo_url:
        return ""
    
    html_parts = []
    
    # Photo (sera affichée en premier visuellement grâce à l'ordre CSS)
    if photo_url:
        html_parts.append(f'<img src="{html.escape(photo_url)}" alt="Photo de profil" class="presentation-photo" loading="lazy">')
    
    # Titre de présentation (sous le h1 principal)
    if title:
        html_parts.append(f'<h1 class="presentation-title">{html.escape(title)}</h1>')
    
    # Texte
    if text:
        html_parts.append(f'<h2 class="presentation-text">{html.escape(text)}</h2>')

    return "".join(html_parts)

def minify_css(css: str) -> str:
    """Minifie le CSS de manière plus agressive"""
    # Supprimer les commentaires CSS
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)
    
    # Supprimer les espaces inutiles
    css = re.sub(r'\s*([{}:;,])\s*', r'\1', css)
    css = re.sub(r';\s*}', '}', css)  # Supprimer ; avant }
    css = re.sub(r'\s+', ' ', css)    # Espaces multiples → un seul
    css = re.sub(r'^\s+|\s+$', '', css)  # Trim début/fin
    
    # Optimisations supplémentaires
    css = re.sub(r'0\.(\d+)', r'.\1', css)    # 0.5 → .5
    css = re.sub(r':0(px|em|rem|%)', ':0', css)  # Supprimer unités de 0
    
    return css

def render_page(doc_title:str, body_html:str, site_title:str, base_url:str, palette_css:str, nav_html:str, favicon_url:str|None, theme_css_url:str|None, description:str|None=None, presentation_html:str="", page_h1:str="", lang:str="en")->str:
    favicon_tag = f'<link rel=icon href="{html.escape(favicon_url)}">' if favicon_url else ""
    theme_link = f'<link rel=stylesheet href="{html.escape(theme_css_url)}">' if theme_css_url else ""
    description_tag = f'<meta name=description content="{html.escape(description)}">' if description else ""
    
    # Utiliser page_h1 pour le h1 dans le body, ou fallback sur doc_title
    h1_text = page_h1 if page_h1 else doc_title
    
    # Si on a du contenu de présentation, on l'intègre dans le header
    if presentation_html:
        header_content = (
            f'<div class="header-content">'
            # f'{h1_element}'
            f'<div class="presentation">{presentation_html}</div>'
            f'</div>'
            f'<h2>All posts</h2>'
        )
    else:
        header_content = f'<h1>All posts</h1>'
    
    # Minifier le CSS de palette avant injection
    minified_palette_css = minify_css(palette_css) if palette_css else ""
    
    return (
        f"<!doctype html><html lang='{html.escape(lang)}'><head><meta charset=utf-8>"
        f"<title>{html.escape(doc_title)}</title>"  # site_title pour SEO
        f"{description_tag}"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<meta name=generator content=TinyBlog>"
        f"{favicon_tag}"
        "<link rel=preconnect href=https://fonts.googleapis.com>"
        "<link rel=preconnect href=https://fonts.gstatic.com crossorigin>"
        "<link href='https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400..800;1,400..800&family=Geist:wght@100..900&family=Ubuntu+Mono:ital,wght@0,400;0,700;1,400;1,700&display=swap' rel=stylesheet>"
        f"{theme_link}"
        f"<script>{THEME_BOOT_JS}</script>"
        f"<style>{minified_palette_css}</style>"
        f"{nav_html}<main><header>{header_content}</header>"
        f"{body_html}<footer></footer></main>"
        "<script src=https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.1/highlight.min.js></script>"
        "<script>hljs.highlightAll();</script>"
        # f"<script>{HLJS_JS}</script>"
        f"<script>{NAV_JS}</script>"
    )

def minify_html(s:str)->str:
    # Protéger le contenu sensible aux espaces
    keep:list[str]=[]
    def stash(m):
        keep.append(m.group(0))
        return f"<!--__TB_KEEP_{len(keep)-1}__-->"
    # préserve <pre>, <code>, <textarea>, <script>, <style>
    s = re.sub(r"(?is)<(pre|code|textarea|script|style)\b.*?>.*?</\1>", stash, s)
    # Minification sûre (entre balises uniquement)
    s = re.sub(r">\s+<", "><", s).strip()
    # Restaurer
    for i,blk in enumerate(keep):
        s = s.replace(f"<!--__TB_KEEP_{i}__-->", blk)
    return s

# ===================== Helpers =====================
def read_site(site_path:Path)->dict:
    return json.loads(site_path.read_text(encoding="utf-8")) if site_path.exists() else {"title":"TinyBlog","description":""}

def slugify(s:str)->str:
    s=s.lower(); s=re.sub(r"[^a-z0-9]+","-",s).strip("-"); return re.sub(r"-{2,}","-",s) or "uncategorized"

def make_asset_url(u:str|None, base_url:str)->str|None:
    if not u: return None
    u=u.strip()
    if not u: return None
    if u.startswith(("http://","https://","data:")): return u
    if u.startswith("/"): return base_url.rstrip("/") + u
    return base_url + u  # p.ex. "assets/img.png" -> "<base_url>assets/img.png"

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

        if f.stem.lower() in ("example", "exemple", "_example", "_exemple"):
            print(f"[SKIP] Ignoring example file: {f.name}")
            continue

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
        # Nouveau: support pour thumbnail_on_article
        thumbnail_on_article = str(meta.get("thumbnail_on_article", "")).lower() in ("true", "1", "yes")
        # Nouveau: support pour min_read et author
        min_read = meta.get("min_read", "")
        author = meta.get("author", "")
        entry = {"slug":f.stem,"title":title,"subtitle":subtitle,"md":body,
                 "categories":cats,"categories_slug":[slugify(c) for c in cats],
                 "excerpt":excerpt_from_md(body),"date_obj":date_obj,"date_str":date_str,
                 "thumbnail":thumbnail,"thumbnail_on_article":thumbnail_on_article,
                 "min_read":min_read,"author":author}
        if is_page:
            pages[f.stem.lower()] = entry
        else:
            posts.append(entry)
    return posts, pages

def build_ordered_list(items, base_url:str, default_thumb_url:str|None=None)->str:
    cards=[]
    for p in items:
        # Thumbnail (avec valeur par défaut si manquante)
        img_url = make_asset_url(p.get("thumbnail"), base_url) or default_thumb_url
        if img_url:
            thumb_html = f'<div class="postthumbnail"><img src="{html.escape(img_url)}" alt="Thumbnail for {html.escape(p["title"])}" loading="lazy"></div>'
        else:
            thumb_html = '<div class="postthumbnail"><div class="postthumbnail-placeholder">📄</div></div>'

        # Categories chips
        chips = " ".join(f'<span class="chip">{html.escape(n)}</span>'
                        for n in p["categories"])
        
        # Meta info - ajouter author et min_read
        meta_parts = [f'<span>{p["date_str"]}</span>']
        if p.get("author"):
            meta_parts.append(f'<span>👤 By {html.escape(p["author"])}</span>')
        if p.get("min_read"):
            meta_parts.append(f'<span>⌛ {html.escape(str(p["min_read"]))} min read</span>')
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

def bytes_ok(path: Path, limit: int):
    size = path.stat().st_size
    
    # Limites recommandées par type
    limits = {
        "index.html": 14 * 1024,
        "article": 30 * 1024,
        "default": limit
    }
    
    if path.name == "index.html":
        threshold = limits["index.html"]
    elif path.name.endswith(".html") and path.parent.name != "category":
        threshold = limits["article"]
    else:
        threshold = limits["default"]
    
    status = "OK" if size <= threshold else "WARN"
    print(f"[{status}] {path.name} = {size} bytes" + 
          (f" > {threshold} bytes (recommended size exceeded)" if status == "WARN" else ""))

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

# ===================== Sitemap generation =====================
def generate_sitemap(site_url: str, posts: list, pages: dict, categories: dict, base_url: str) -> str:
    """Génère un sitemap.xml avec toutes les pages du site"""
    from urllib.parse import urljoin

    # Nettoyer l'URL de base pour éviter les doubles slashes
    site_url = site_url.rstrip('/')
    
    entries = []
    
    # Page d'accueil - priorité la plus haute, mise à jour fréquente
    entries.append({
        'loc': site_url + base_url.rstrip('/') + '/',
        'lastmod': posts[0]['date_obj'].strftime('%Y-%m-%d') if posts else None,
        'changefreq': 'daily',
        'priority': '1.0'
    })
    
    # Posts - priorité haute, changement occasionnel
    for post in posts:
        entries.append({
            'loc': f"{site_url}{base_url.rstrip('/')}/{post['slug']}.html",
            'lastmod': post['date_obj'].strftime('%Y-%m-%d'),
            'changefreq': 'monthly',
            'priority': '0.8'
        })
    
    # Pages statiques - priorité moyenne, changement rare
    for slug, page_data in pages.items():
        entries.append({
            'loc': f"{site_url}{base_url.rstrip('/')}/{slug}.html",
            'lastmod': page_data['date_obj'].strftime('%Y-%m-%d'),
            'changefreq': 'yearly',
            'priority': '0.6'
        })
    
    # Pages de catégories - priorité basse, changement avec nouveaux posts
    for cat_slug, (cat_name, cat_posts) in categories.items():
        if cat_posts:  # Seulement si la catégorie a des posts
            # Date du post le plus récent dans cette catégorie
            latest_post = max(cat_posts, key=lambda p: p['date_obj'])
            entries.append({
                'loc': f"{site_url}{base_url.rstrip('/')}/category/{cat_slug}.html",
                'lastmod': latest_post['date_obj'].strftime('%Y-%m-%d'),
                'changefreq': 'weekly',
                'priority': '0.4'
            })
    
    # Génération du XML
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]
    
    for entry in entries:
        xml_lines.append('  <url>')
        xml_lines.append(f'    <loc>{html.escape(entry["loc"])}</loc>')
        
        if entry.get('lastmod'):
            xml_lines.append(f'    <lastmod>{entry["lastmod"]}</lastmod>')
        
        if entry.get('changefreq'):
            xml_lines.append(f'    <changefreq>{entry["changefreq"]}</changefreq>')
        
        if entry.get('priority'):
            xml_lines.append(f'    <priority>{entry["priority"]}</priority>')
        
        xml_lines.append('  </url>')
    
    xml_lines.append('</urlset>')
    
    return '\n'.join(xml_lines)

# ===================== Robots.txt generation =====================
def generate_robots_txt(robots_config: dict, site_url: str, base_url: str) -> str:
    """Génère un fichier robots.txt à partir de la configuration"""
    if not robots_config:
        # Configuration par défaut
        lines = [
            "User-agent: *",
            "Allow: /",
            "",
            f"Sitemap: {site_url.rstrip('/')}{base_url.rstrip('/')}/sitemap.xml"
        ]
        return "\n".join(lines)
    
    lines = []
    
    # User-Agent
    user_agent = robots_config.get("userAgent", "*")
    lines.append(f"User-agent: {user_agent}")
    
    # Allow rules
    allow_rules = robots_config.get("allow", [])
    if isinstance(allow_rules, str):
        allow_rules = [allow_rules]
    for rule in allow_rules:
        lines.append(f"Allow: {rule}")
    
    # Disallow rules
    disallow_rules = robots_config.get("disallow", [])
    if isinstance(disallow_rules, str):
        disallow_rules = [disallow_rules]
    for rule in disallow_rules:
        lines.append(f"Disallow: {rule}")
    
    # Crawl-delay si spécifié
    if "crawlDelay" in robots_config:
        lines.append(f"Crawl-delay: {robots_config['crawlDelay']}")
    
    # Ligne vide avant le sitemap
    if lines:
        lines.append("")
    
    # Sitemap
    include_sitemap = robots_config.get("sitemap", True)
    if include_sitemap and site_url:
        lines.append(f"Sitemap: {site_url.rstrip('/')}{base_url.rstrip('/')}/sitemap.xml")
    
    # Commentaires personnalisés
    comments = robots_config.get("comments", [])
    if isinstance(comments, str):
        comments = [comments]
    for comment in comments:
        lines.insert(0, f"# {comment}")
    
    return "\n".join(lines)

# ===================== Build =====================
def build(args):
    root=Path.cwd()
    content_dir=root/args.content
    public_dir=root/args.public
    out_dir=root/args.out
    site=read_site(root/args.site)
    site_description = site.get("description", "")
    site_title = site.get("title", "TinyBlog")
    site_title_html = site.get("site_title", site_title)
    site_url = site.get("siteUrl", "")  # Nouvelle variable pour le sitemap
    site_lang = site.get("lang", "en")  # Langue du site, par défaut 'en'
    
    # Génération de la section présentation
    presentation_html = build_presentation_section(site.get("presentation", {}), args.base_url)
    
    # Génération des liens sociaux
    social_links_html = build_social_links(site.get("social", {}), args.base_url)
    
    pal_css=palette_override(site.get("palette"), site.get("paletteDark"))

    # URLs d'assets depuis la config
    favicon_url = make_asset_url(site.get("favicon"), args.base_url)
    default_thumb_url = make_asset_url(site.get("defaultThumbnail"), args.base_url)

    # Résolution du CSS de thème:
    # Priorité: site.theme -> site.themeCss -> --theme-css
    theme_css_url=None
    theme_rel=None
    theme = site.get("theme")
    if isinstance(theme, str) and theme.strip():
        t = theme.strip()
        if t.startswith(("http://","https://")):
            theme_css_url = t
        elif t.endswith(".css"):
            theme_rel = t.lstrip("/") if not t.startswith("assets/") else t[len("assets/"):]
        else:
            # nom de thème => assets/themes/<nom>.css
            theme_rel = f"themes/{slugify(t)}.css"
    else:
        theme_css_setting = site.get("themeCss") or args.theme_css  # ex: "assets/css/theme.css" ou URL complète
        if theme_css_setting:
            if theme_css_setting.startswith(("http://","https://")):
                theme_css_url = theme_css_setting
            else:
                rel = theme_css_setting.lstrip("/")
                theme_rel = rel[len("assets/"):] if rel.startswith("assets/") else rel

    if theme_rel:
        # URL publique
        theme_css_url = args.base_url.rstrip("/") + "/assets/" + theme_rel
        # Auto-génération si manquant (écrit BASE_CSS minifié)
        css_fs = public_dir / theme_rel
        if not css_fs.exists():
            css_fs.parent.mkdir(parents=True, exist_ok=True)
            # Minifier le CSS de base avant l'écriture
            minified_base_css = minify_css(BASE_CSS)
            css_fs.write_text(minified_base_css, encoding="utf-8")
            print(f"[GEN]  Generated minified theme CSS: {css_fs}")

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

    nav_html=build_nav(site_title, args.base_url, categories_sorted, pages, social_links_html)
    
    rendered={}
    
    # index - avec présentation, masque le h1
    idx_body=build_ordered_list(posts, args.base_url, default_thumb_url)
    rendered["/index.html"]=minify_html(render_page(
        site_title_html,           # <title> dans le head
        idx_body,
        site_title,
        args.base_url,
        pal_css,
        nav_html,
        favicon_url,
        theme_css_url,
        site_description,
        presentation_html,
        site_title, # <h1> dans le body (même que navigation)
        lang=site_lang
    ))

    # pages - utilise titre de page pour <h1>, titre complet pour <title>
    for slug, page_data in pages.items():
        page_title_meta = f"{page_data['title']} - {site_title_html}"  # Pour <title>
        page_title_h1 = page_data['title']  # Pour <h1>
        rendered[f"/{slug}.html"]=minify_html(render_page(
            page_title_meta,
            md_render(page_data["md"]), 
            site_title, 
            args.base_url, 
            pal_css, 
            nav_html, 
            favicon_url, 
            theme_css_url, 
            site_description,
            "",  # pas de présentation
            page_title_h1,
            lang=site_lang
        ))

    # posts - utilise titre d'article pour <h1>, titre complet pour <title>
    for p in posts:
        chips=" ".join(f'<a class="chip" href="{args.base_url}category/{s}.html">{html.escape(n)}</a>'
                       for n,s in zip(p["categories"],p["categories_slug"]))
        
        # Meta info pour les articles - ajouter author et min_read
        meta_parts = [f'<span>{p["date_str"]}</span>']
        if p.get("author"):
            meta_parts.append(f'<span>👤 By {html.escape(p["author"])}</span>')
        if p.get("min_read"):
            meta_parts.append(f'<span>⌛ {html.escape(str(p["min_read"]))} min read</span>')
        if chips:
            meta_parts.append(chips)
        
        head=f'<div class="postmeta">{"".join(meta_parts)}</div>'
        
        # Ajouter la miniature dans l'article si thumbnail_on_article est true
        thumbnail_html = ""
        if p.get("thumbnail_on_article") and p.get("thumbnail"):
            img_url = make_asset_url(p["thumbnail"], args.base_url)
            if img_url:
                thumbnail_html = f'<div class="article-thumbnail"><img src="{html.escape(img_url)}" alt="Thumbnail for {html.escape(p["title"])}" loading="lazy"></div>'
        
        body_html=head+thumbnail_html+md_render(p["md"])
        post_title_meta = f"{p['title']} - {site_title_html}"  # Pour <title>
        post_title_h1 = p['title']  # Pour <h1>
        rendered[f"/{p['slug']}.html"]=minify_html(render_page(
            post_title_meta,
            body_html, 
            site_title, 
            args.base_url, 
            pal_css, 
            nav_html, 
            favicon_url, 
            theme_css_url, 
            site_description,
            "",  # pas de présentation
            post_title_h1,
            lang=site_lang
        ))

    # categories - utilise nom de catégorie pour <h1>, titre complet pour <title>
    for slug,(name,plist) in cat_map.items():
        plist_sorted=sorted(plist,key=lambda p:p["date_obj"],reverse=True)
        body=build_ordered_list(plist_sorted, args.base_url, default_thumb_url)
        category_title_meta = f"Category · {name} - {site_title_html}"  # Pour <title>
        category_title_h1 = f"Category · {name}"  # Pour <h1>
        rendered[f"/category/{slug}.html"]=minify_html(render_page(
            category_title_meta,
            body, 
            site_title, 
            args.base_url, 
            pal_css, 
            nav_html, 
            favicon_url, 
            theme_css_url, 
            site_description,
            "",  # pas de présentation
            category_title_h1
        ))

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
    
    # Génération du sitemap.xml si siteUrl est définie
    if site_url:
        sitemap_xml = generate_sitemap(site_url, posts, pages, cat_map, args.base_url)
        sitemap_file = out_dir / "sitemap.xml"
        sitemap_file.write_text(sitemap_xml, encoding="utf-8")
        print(f"[OK]   sitemap.xml generated with {len(posts) + len(pages) + len(cat_map) + 1} URLs")
    else:
        print("[SKIP] sitemap.xml - no siteUrl defined in site.json")
    
    # Génération du robots.txt
    robots_config = site.get("robotsTxt", {})
    robots_txt = generate_robots_txt(robots_config, site_url, args.base_url)
    robots_file = out_dir / "robots.txt"
    robots_file.write_text(robots_txt, encoding="utf-8")
    print(f"[OK]   robots.txt generated")
    
    # Toujours créer le dossier assets (même s'il n'y a rien à copier)
    (out_dir/"assets").mkdir(parents=True, exist_ok=True)
    if public_dir.exists():
        for src in public_dir.rglob("*"):
            if src.is_file():
                rel=src.relative_to(public_dir)
                dst=out_dir/"assets"/rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                
                # Minifier les fichiers CSS lors de la copie
                if src.suffix.lower() == '.css':
                    css_content = src.read_text(encoding="utf-8")
                    minified_css = minify_css(css_content)
                    dst.write_text(minified_css, encoding="utf-8")
                    print(f"[MIN]  Minified CSS: {rel}")
                else:
                    shutil.copy2(src,dst)
    print(f"[DONE] {len(posts)} post(s), {len(cat_map)} category page(s) + index @ {time.strftime('%Y-%m-%d %H:%M:%S')}")

def build_social_links(social_config: dict, base_url: str) -> str:
    """Génère les liens vers les réseaux sociaux avec icônes SVG"""
    if not social_config:
        return ""
    
    # Mapping étendu pour toutes les icônes disponibles
    icon_files = {
        "twitter": "twitter",
        "twitter-x": "twitter-x",
        "x": "twitter-x",
        "github": "github",
        "gitlab": "gitlab",
        "linkedin": "linkedin",
        "facebook": "facebook",
        "instagram": "instagram",
        "youtube": "youtube",
        "discord": "discord",
        "dribbble": "dribbble",
        "medium": "medium",
        "messenger": "messenger",
        "pinterest": "pinterest",
        "quora": "quora",
        "reddit": "reddit",
        "skype": "skype",
        "spotify": "spotify",
        "telegram": "telegram",
        "tiktok": "tiktok",
        "twitch": "twitch",
        "whatsapp": "whatsapp"
    }
    
    links = []
    for platform, url in social_config.items():
        if not url:
            continue
        
        platform_lower = platform.lower()
        icon_name = icon_files.get(platform_lower, platform_lower)
        icon_url = f"{base_url}assets/icons/{icon_name}.svg"
        title = platform.capitalize()
        
        links.append(
            f'<a class="social-link" href="{html.escape(url)}" '
            f'title="{html.escape(title)}" target="_blank" rel="noopener">'
            f'<img src="{html.escape(icon_url)}" alt="{html.escape(title)}" class="social-icon">'
            f'</a>'
        )
    
    if not links:
        return ""
    
    return f'<div class="social-links">{"".join(links)}</div>'

if __name__=="__main__":
    build(parse_args())
