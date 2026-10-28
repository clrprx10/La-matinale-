#!/usr/bin/env python3
"""La Matinale : collecte prudente de liens sourcés, sans résumé inventé."""
import json, re, sys, html, random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo
import requests, feedparser
from bs4 import BeautifulSoup
from gtts import gTTS

ROOT=Path(__file__).resolve().parent
DOCS=ROOT/"docs"
CFG=json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
NOW=datetime.now(ZoneInfo(CFG.get("timezone","Europe/Paris")))
HEADERS={"User-Agent":"LaMatinale/2.0 (personal educational news reader)"}
SESSION=requests.Session()
SESSION.headers.update(HEADERS)
EDU_WORDS=("école","scolaire","élève","enseign","éducat","pédagog","formation","universit","collège","lycée","apprentiss","recherche","étude","rapport","note d'information","direction","établissement")
SKIP=("connexion","contact","mentions légales","accessibilité","cookies","newsletter","accueil","rechercher","menu","en savoir plus","tous les articles","toute l'actualité")
DATE_RE=re.compile(r'\b(20\d{2})-(\d{2})-(\d{2})\b')
FRENCH_DATE=re.compile(r'\b(\d{1,2})\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(20\d{2})\b',re.I)
MONTHS={m:i+1 for i,m in enumerate("janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split())}

def get(url):
    r=SESSION.get(url,timeout=18)
    r.raise_for_status()
    return r

def date_from(s):
    if not s:return None
    s=str(s)
    try:
        x=datetime.fromisoformat(s.replace("Z","+00:00"))
        return x.date()
    except (ValueError,TypeError):pass
    m=DATE_RE.search(s)
    if m:
        try:return datetime(*map(int,m.groups())).date()
        except ValueError:pass
    m=FRENCH_DATE.search(s.lower())
    if m:
        try:return datetime(int(m.group(3)),MONTHS[m.group(2)],int(m.group(1))).date()
        except ValueError:pass
    return None

def eligible(d):
    # Never present undated pages as dated news.
    return d is not None and NOW.date()-timedelta(days=365)<=d<=NOW.date()

def clean(s):
    return re.sub(r"\s+"," ",html.unescape(s or "")).strip()

def parse_rss(source):
    content=get(source["url"]).content
    feed=feedparser.parse(content)
    result=[]
    for e in feed.entries[:35]:
        title=clean(e.get("title",""))
        link=e.get("link","")
        dt=date_from(e.get("published","") or e.get("updated",""))
        if not dt:
            for key in ("published_parsed","updated_parsed"):
                p=e.get(key)
                if p:
                    try:dt=datetime(*p[:6]).date()
                    except Exception:pass
        if title and link.startswith("http") and eligible(dt):
            summary=clean(BeautifulSoup(e.get("summary",""),"html.parser").get_text(" ",strip=True))
            result.append(dict(title=title,url=link,date=dt.isoformat(),source=source["name"],theme=source["theme"],summary=summary[:300]))
    return result

def page_details(url):
    try:
        r=get(url)
        soup=BeautifulSoup(r.text,"html.parser")
        dates=[]
        for sel in ('meta[property="article:published_time"]','meta[name="date"]','meta[name="DC.date"]','meta[itemprop="datePublished"]','time[datetime]'):
            for tag in soup.select(sel)[:3]:
                d=date_from(tag.get("content") or tag.get("datetime") or tag.get_text(" ",strip=True))
                if d:dates.append(d)
        if not dates:
            # Limit to header/lead text, not unrelated sidebar dates.
            top=soup.find("main") or soup.find("article") or soup
            d=date_from(top.get_text(" ",strip=True)[:900])
            if d:dates.append(d)
        desc=soup.select_one('meta[name="description"]')
        summary=clean(desc.get("content","")) if desc else ""
        return (dates[0] if dates else None),summary[:300]
    except Exception:return None,""

def parse_html(source):
    soup=BeautifulSoup(get(source["url"]).text,"html.parser")
    base=urlparse(source["url"]).netloc
    candidates=[]
    seen=set()
    container=soup.find("main") or soup
    for a in container.find_all("a",href=True):
        title=clean(a.get_text(" ",strip=True))
        url=urljoin(source["url"],a["href"].split("#")[0])
        host=urlparse(url).netloc
        if not (host==base or host.endswith("."+base)):continue
        if url in seen or len(title)<22 or len(title)>190:continue
        if any(title.lower()==bad or title.lower().startswith(bad+" ") for bad in SKIP):continue
        if url.rstrip("/")==source["url"].rstrip("/"):continue
        if source["theme"]=="Éducation" and not any(w in title.lower() for w in EDU_WORDS):
            # Other education links are still considered if title is specific.
            if len(title)<42:continue
        seen.add(url)
        candidates.append((title,url))
        if len(candidates)>=12:break
    items=[]
    for title,url in candidates[:8]:
        dt,summary=page_details(url)
        if eligible(dt):
            items.append(dict(title=title,url=url,date=dt.isoformat(),source=source["name"],theme=source["theme"],summary=summary))
    return items

def collect():
    items=[]
    for source in CFG["sources"]:
        try:
            found=parse_rss(source) if source.get("type")=="rss" else parse_html(source)
            print(f'{source["name"]}: {len(found)} publications datées vérifiées',flush=True)
            items.extend(found)
        except Exception as e:
            print(f'AVERTISSEMENT {source["name"]}: {type(e).__name__}: {e}',flush=True)
    return items

def choose(items):
    seen=set()
    unique=[]
    for x in sorted(items,key=lambda x:x["date"],reverse=True):
        k=re.sub(r'\W+','',x["title"].lower())[:75]
        if k in seen:continue
        seen.add(k);unique.append(x)
    edu=[x for x in unique if x["theme"]=="Éducation"]
    other=[x for x in unique if x["theme"]!="Éducation"]
    if not edu:
        print("ERREUR : aucune publication Éducation datée et vérifiable. Aucune édition inventée.",file=sys.stderr)
        sys.exit(2)
    # Education always first; alternate other subjects where available.
    chosen=edu[:2]
    used={x["url"] for x in chosen}
    for x in other:
        if x["url"] not in used and x["theme"] not in {y["theme"] for y in chosen}:
            chosen.append(x);used.add(x["url"])
        if len(chosen)>=5:break
    for x in edu[2:]:
        if len(chosen)>=4:break
        chosen.append(x)
    return chosen[:5]

def script_for(chosen):
    lines=[f"Bonjour. Voici La Matinale du {NOW.strftime('%d/%m/%Y')}.",
           "Cette édition est une revue de publications identifiées. Les titres, les dates et les liens figurent dans la transcription.",
           "Les informations présentées sont attribuées à leurs organismes de publication. Les titres ne constituent pas une vérification indépendante de toutes les affirmations."]
    for i,x in enumerate(chosen,1):
        lines.append(f"Sujet {i}. Rubrique {x['theme']}. Source : {x['source']}. Publication du {datetime.fromisoformat(x['date']).strftime('%d/%m/%Y')}.")
        lines.append(x["title"].rstrip(".")+".")
        if x["summary"] and len(x["summary"])>30:
            lines.append("Présentation publiée par la source : "+x["summary"])
        else:
            lines.append("Pour approfondir ce sujet, consultez la publication originale dans les liens de l'édition.")
    lines.append("Vous trouverez les références et les dates sur la page de La Matinale. À demain.")
    return "\n\n".join(lines)

def main():
    items=collect()
    chosen=choose(items)
    text=script_for(chosen)
    DOCS.mkdir(exist_ok=True)
    gTTS(text=text,lang="fr",slow=False).save(str(DOCS/"matinale.mp3"))
    data={"title":CFG.get("title","La Matinale"),"date":NOW.date().isoformat(),"generated_at":NOW.isoformat(),
          "audio":"matinale.mp3","transcript":text,"stories":chosen,
          "notice":"Revue de titres et de présentations attribuées aux sources. Pas une synthèse journalistique indépendante."}
    (DOCS/"edition.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Édition créée : {len(chosen)} publications, {len(text.split())} mots.",flush=True)

if __name__=="__main__":
    main()
