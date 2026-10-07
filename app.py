import os, json, uuid, glob, csv, io
from datetime import datetime, timezone
import time
from flask import Flask, jsonify, render_template, request, send_file, Response
from dotenv import load_dotenv
from services.analytics import normalize, normalize_linkedin, summary, sentiment_summary, cross, insights, PLATFORMS, sentiment
from scrapers.live import instagram, x, linkedin, youtube

BASE=os.path.dirname(os.path.abspath(__file__))
STORAGE=os.path.join(BASE,"storage")
os.makedirs(STORAGE,exist_ok=True)
load_dotenv(os.path.join(BASE,".env"))
app=Flask(__name__,template_folder="templates",static_folder="static")
app.secret_key=os.getenv("SECRET_KEY","dev-secret")


def payload(records, source_ref="", run_id=None):
    s=summary(records); return {"run_id":run_id or uuid.uuid4().hex[:12],"created_at":datetime.now(timezone.utc).isoformat(),"source_ref":source_ref,"records":records,"summary":s,"sentiment":sentiment_summary(records),"insights":insights(records)}

def json_dump(path,data):
    with open(path,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)

def saved_runs():
    out=[]
    for p in glob.glob(os.path.join(STORAGE,"*.json")):
        try:
            d=json.load(open(p,encoding="utf-8")); out.append({"run_id":d.get("run_id"),"created_at":d.get("created_at"),"platforms":sorted(set(r.get("platform") for r in d.get("records",[]))),"posts":len(d.get("records",[])),"source_ref":d.get("source_ref",""),"file":os.path.basename(p)})
        except Exception: pass
    return sorted(out,key=lambda x:x.get("created_at",""),reverse=True)

@app.get("/")
def home(): return render_template("index.html")

@app.get("/api/health")
def health():
    def configured(name, fallback):
        v=os.getenv(name, fallback).strip()
        return bool(v) and "YOUR_" not in v.upper() and "CHANGE-ME" not in v.upper()
    return jsonify({
        "apify": bool(os.getenv("APIFY_TOKEN", "").strip()),
        "youtube": bool(os.getenv("YOUTUBE_API_KEY", "").strip()),
        "platforms": list(PLATFORMS),
        "actors": {
            "instagram": configured("INSTAGRAM_ACTOR_ID", ""),
            "x": configured("X_ACTOR_ID", ""),
            "linkedin": configured("LINKEDIN_ACTOR_ID", "")
        },
        "actor_ids": {p: os.getenv(k, "") for p,k in {
            "instagram":"INSTAGRAM_ACTOR_ID","x":"X_ACTOR_ID","linkedin":"LINKEDIN_ACTOR_ID"
        }.items()}
    })

@app.post("/api/analyze/<platform>")
def analyze(platform):
    if platform not in PLATFORMS:return jsonify({"error":"Unsupported platform"}),404
    data=request.get_json(silent=True) or {}
    ref=(data.get("reference") or "").strip()
    limit=max(1,min(int(data.get("limit",25)),100))
    if not ref:return jsonify({"error":"Enter a username, handle, or profile/channel URL."}),400
    started=time.time()
    try:
        if platform=="instagram": records=instagram(ref,limit)
        elif platform=="x": records=x(ref,limit)
        elif platform=="linkedin": records=linkedin(ref,limit)
        else:
            cp=max(0,min(int(data.get("comments_per_video",0)),100)); rows,ch=youtube(ref,min(limit,50),cp)
            records=normalize("youtube",{"channel":{"title":ch.get("snippet",{}).get("title",ref),"subscribers":ch.get("statistics",{}).get("subscriberCount",0)},"items":rows},ref)[1]
            for i,p in enumerate(records):
                raw=rows[i] if i<len(rows) else {}; texts=raw.get("comments_text",[]); labels=[sentiment(t)[0] for t in texts]; p["comment_sentiment"]={"positive":labels.count("Positive"),"neutral":labels.count("Neutral"),"negative":labels.count("Negative"),"total":len(labels)}
        result=payload(records,ref)
        result["elapsed_seconds"]=round(time.time()-started,2)
        if not records:
            result["warning"]="The live connector completed but returned 0 items. Check the Actor input schema/output in Apify Console."
        return jsonify(result)
    except Exception as exc:
        msg=str(exc) or "Live analysis failed."
        return jsonify({"error":msg,"platform":platform,"reference":ref,"elapsed_seconds":round(time.time()-started,2)}),502

@app.post("/api/save")
def save():
    data=request.get_json(silent=True) or {}; records=data.get("records") or []
    if not records:return jsonify({"error":"Nothing to save. Run at least one live analysis first."}),400
    run=payload(records,data.get("source_ref",""),data.get("run_id"))
    path=os.path.join(STORAGE,run["run_id"]+".json"); json_dump(path,run)
    return jsonify({"ok":True,"run_id":run["run_id"],"file":os.path.basename(path),"created_at":run["created_at"]})

@app.get("/api/saved")
def saved(): return jsonify(saved_runs())

@app.get("/api/saved/<run_id>")
def saved_one(run_id):
    path=os.path.join(STORAGE,run_id+".json")
    if not os.path.exists(path):return jsonify({"error":"Saved analysis not found"}),404
    return jsonify(json.load(open(path,encoding="utf-8")))

@app.delete("/api/saved/<run_id>")
def delete_saved(run_id):
    path=os.path.join(STORAGE,run_id+".json")
    if not os.path.exists(path):return jsonify({"error":"Not found"}),404
    os.remove(path); return jsonify({"ok":True})

@app.post("/api/save-all")
def save_all():
    data=request.get_json(silent=True) or {}; records=data.get("records") or []
    if not records:return jsonify({"error":"No current analytics to save."}),400
    run=payload(records,"Cross-platform workspace",data.get("run_id")); path=os.path.join(STORAGE,run["run_id"]+".json"); json_dump(path,run); return jsonify({"ok":True,"run_id":run["run_id"],"file":os.path.basename(path)})

@app.get("/api/export")
def export_data():
    run_id=request.args.get("run_id","").strip(); path=os.path.join(STORAGE,run_id+".json")
    if not run_id or not os.path.exists(path): return jsonify({"error":"Saved analysis not found"}),404
    return send_file(path,as_attachment=True,download_name=f"social-media-analysis-{run_id}.json",mimetype="application/json")

CSV_COLUMNS=["platform","username","name","followers","post_id","date","media_type","text","likes","comments","shares","views","interactions","engagement_rate","sentiment","compound","url"]

@app.post("/api/insights")
def insights_api():
    data=request.get_json(silent=True) or {}
    records=data.get("records") or []
    if not records: return jsonify({"error":"No records supplied."}),400
    return jsonify(insights(records))

@app.post("/api/export-csv")
def export_csv():
    data=request.get_json(silent=True) or {}
    records=data.get("records") or []
    if not records: return jsonify({"error":"Nothing to export. Run an analysis first."}),400
    buf=io.StringIO()
    w=csv.DictWriter(buf,fieldnames=CSV_COLUMNS,extrasaction="ignore")
    w.writeheader()
    for r in records:
        row={k:r.get(k,"") for k in CSV_COLUMNS}
        row["text"]=(row.get("text") or "").replace("\n"," ").strip()
        w.writerow(row)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Response(buf.getvalue(),mimetype="text/csv",
        headers={"Content-Disposition":f"attachment; filename=social-media-analysis-{stamp}.csv"})

@app.get("/api/cross")
def cross_api():
    records=[]
    for p in glob.glob(os.path.join(STORAGE,"*.json")):
        try: records+=json.load(open(p,encoding="utf-8")).get("records",[])
        except Exception: pass
    return jsonify({"records":records,"summary":summary(records),"sentiment":sentiment_summary(records),"creators":cross(records),"insights":insights(records)})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT",5000)),debug=True)
