"""Bulletin factuel fondé sur des extraits sourcés; ne produit aucune analyse inventée."""
import json, re, os, sys, html, hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
import feedparser
import requests
from bs4 import BeautifulSoup
from gtts import gTTS

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'docs'
CFG=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
TZ=ZoneInfo(CFG.get('timezone','Europe/Paris'))
NOW=datetime.now(TZ)
HEADERS={'User-Agent':'LaMatinale/1.0 (personal RSS reader)'}
THEMES=['France','International','Économie','Géopolitique','Culture','Histoire']

def clean(s):
    s=BeautifulSoup(str(s or ''),'html.parser').get_text(' ',strip=True)
    return re.sub(r'\s+',' ',html.unescape(s)).strip()

def get_items(source):
    try:
        r=requests.get(source['url'],timeout=18,headers=HEADERS)
        r.raise_for_status()
        feed=feedparser.parse(r.content)
        if not feed.entries: return [],f"{source['name']} : aucun flux RSS lisible (adresse à vérifier)"
        items=[]
        for e in feed.entries[:35]:
            title=clean(e.get('title',''))
            desc=clean(e.get('summary','') or e.get('description',''))
            link=e.get('link','')
            stamp=e.get('published_parsed') or e.get('updated_parsed')
            dt=datetime(*stamp[:6],tzinfo=timezone.utc).astimezone(TZ) if stamp else None
            if not (title and desc and link and urlparse(link).scheme in ('https','http')):continue
            if dt and (NOW-dt).days>21:continue
            items.append({'title':title,'summary':desc[:1100],'link':link,'source':source['name'],'theme':source['theme'],'date':dt.strftime('%d/%m/%Y') if dt else 'date non fournie','age':(NOW-dt).total_seconds()/86400 if dt else 14})
        return items,None
    except Exception as ex:
        return [],f"{source['name']} : {type(ex).__name__}"

def compose(items):
    by={}
    for x in items: by.setdefault(x['theme'],[]).append(x)
    for group in by.values():group.sort(key=lambda x:x['age'])
    # 1 sujet éducation et 3 à 4 sujets alternés selon date; jamais de faux sujet.
    chosen=[]; used=set()
    def pick(theme):
        for x in by.get(theme,[]):
            key=re.sub(r'\W+','',x['title'].lower())[:65]
            if key not in used:
                used.add(key);chosen.append(x);return True
        return False
    pick('Éducation')
    rotation=THEMES[NOW.toordinal()%len(THEMES):]+THEMES[:NOW.toordinal()%len(THEMES)]
    for t in rotation: 
        if len(chosen)>=5:break
        pick(t)
    return chosen

def script_for(chosen):
    intro=f"Bonjour. Voici La Matinale du {NOW.strftime('%d/%m/%Y')}. Ce bulletin reprend des informations attribuées à leurs sources, sans analyse ni conclusion ajoutée."
    parts=[intro]
    for i,x in enumerate(chosen,1):
        summary=x['summary'].rstrip(' .')
        # Nous ne complétons jamais les extraits par des détails non sourcés.
        parts.append(f"Sujet {i}. Rubrique {x['theme']}. Selon {x['source']}, publication datée du {x['date']}. {x['title']}. {summary}. Pour consulter le document d'origine, utilisez le lien affiché dans l'application.")
    parts.append("C'est la fin de cette édition. Les références complètes figurent sous le lecteur. Merci de votre écoute.")
    return '\n\n'.join(parts)

def main():
    OUT.mkdir(exist_ok=True)
    all_items=[]; errors=[]
    for s in CFG['sources']:
        a,e=get_items(s);all_items+=a
        if e:errors.append(e)
    chosen=compose(all_items)
    # En cas d'absence de source éducation, pas de prétendue édition conforme.
    if not any(x['theme']=='Éducation' for x in chosen):
        (OUT/'status.json').write_text(json.dumps({'date':NOW.isoformat(),'status':'indisponible','reason':'Aucune source Éducation exploitable','errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
        print('Aucune source Éducation exploitable : édition non publiée.',file=sys.stderr)
        sys.exit(2)
    text=script_for(chosen)
    # gTTS est gratuit mais dépend d'un service tiers non garanti.
    temp=OUT/'matinale.tmp.mp3'
    gTTS(text=text,lang='fr',slow=False).save(str(temp))
    temp.replace(OUT/'matinale.mp3')
    (OUT/'edition.json').write_text(json.dumps({'date':NOW.strftime('%d/%m/%Y'),'created_at':NOW.isoformat(),'title':CFG['title'],'script':text,'items':chosen,'warnings':errors,'audio':'matinale.mp3'},ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'status.json').write_text(json.dumps({'date':NOW.isoformat(),'status':'ok','sources':len(chosen),'warnings':errors},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Publié : {len(chosen)} sujets, {len(text.split())} mots.')
    if len(text.split())<1000:print('ATTENTION : édition courte; durée 10-15 min non atteinte sans sources longues.')

if __name__=='__main__':main()
