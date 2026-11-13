#!/usr/bin/env python3
"""footage_dl.py — โหลดฟุตเทจเฉพาะช่วงเวลา + บันทึกตารางเครดิตให้อัตโนมัติ (ช่องลืมไม่ลง)

ติดตั้งครั้งเดียว (Windows PowerShell):
    pip install -U yt-dlp
    winget install Gyan.FFmpeg        # ต้องมี ffmpeg ใน PATH

ใช้งาน:
    # คลิปเดียว: ลิงก์ + ช่วงเวลา (วินาทีหรือ mm:ss)
    python footage_dl.py "https://www.youtube.com/watch?v=XXXX" 0:12-0:18 --note "ตำรวจหน้าบ้านที่เกิดเหตุ"

    # หลายคลิป: ไฟล์ clips.csv คอลัมน์ url,start,end,note
    python footage_dl.py --csv clips.csv

ผลลัพธ์ (โฟลเดอร์ footage\\ ข้างสคริปต์ หรือใช้ --out):
    footage\\<ชื่อ>.mp4     คลิปที่ตัดเฉพาะช่วง
    credits.csv            ตารางที่มา: ช่อง ลิงก์ วันที่ ช่วงเวลา ไฟล์ หมายเหตุ
    credits.txt            บรรทัดเครดิตพร้อมวางใน description (ไม่ซ้ำ)

หมายเหตุ: ดูฟุตเทจก่อนใช้ทุกครั้ง ตามกฎช่อง ห้ามมีศพ/บาดแผล/เหยื่อขณะเกิดเหตุ/ที่เกิดเหตุ
"""
import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yt_dlp
    from yt_dlp.utils import download_range_func
except ImportError:
    sys.exit("ยังไม่ได้ติดตั้ง yt-dlp:  pip install -U yt-dlp")

CREDIT_FIELDS = ["downloaded_at", "channel", "title", "upload_date", "url", "range", "file", "note"]


def to_seconds(text: str) -> float:
    """'90', '1:30', '0:01:30' -> วินาที"""
    parts = [float(p) for p in text.strip().split(":")]
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    return secs


def safe(name: str, limit: int = 60) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name).strip()
    return (name[:limit].strip() or "clip")


def fetch(url: str, start: str, end: str, note: str, out_dir: Path) -> dict:
    t0, t1 = to_seconds(start), to_seconds(end)
    if t1 <= t0:
        raise ValueError(f"ช่วงเวลาไม่ถูกต้อง: {start}-{end}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    opts = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "download_ranges": download_range_func(None, [(t0, t1)]),
        "force_keyframes_at_cuts": True,  # ตัดตรงเฟรมจริง (ต้องมี ffmpeg)
        "outtmpl": str(out_dir / f"%(uploader|channel)s_%(id)s_{stamp}.%(ext)s"),
        "restrictfilenames": False,
        "windowsfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    channel = info.get("uploader") or info.get("channel") or "ไม่ทราบช่อง"
    return {
        "downloaded_at": datetime.now().isoformat(timespec="seconds"),
        "channel": channel,
        "title": info.get("title", ""),
        "upload_date": info.get("upload_date", ""),
        "url": info.get("webpage_url") or url,
        "range": f"{start}-{end}",
        "file": str(path),
        "note": note,
    }


def log_credit(row: dict, out_dir: Path) -> None:
    csv_path = out_dir.parent / "credits.csv" if out_dir.name == "footage" else out_dir / "credits.csv"
    txt_path = csv_path.with_name("credits.txt")
    is_new = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8-sig") as f:  # utf-8-sig เปิดใน Excel ไม่เพี้ยน
        w = csv.DictWriter(f, fieldnames=CREDIT_FIELDS)
        if is_new:
            w.writeheader()
        w.writerow(row)
    line = f"🎬 ฟุตเทจ: {row['channel']} — {row['url']}"
    existing = txt_path.read_text(encoding="utf-8").splitlines() if txt_path.exists() else []
    if line not in existing:
        with txt_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="โหลดฟุตเทจเป็นช่วง + บันทึกเครดิต")
    ap.add_argument("url", nargs="?", help="ลิงก์วิดีโอ")
    ap.add_argument("range", nargs="?", help="ช่วงเวลา เช่น 0:12-0:18 หรือ 12-18")
    ap.add_argument("--note", default="", help="หมายเหตุว่าใช้ฉากไหน")
    ap.add_argument("--csv", help="ไฟล์ csv: url,start,end,note")
    ap.add_argument("--out", default=str(Path(__file__).parent / "footage"), help="โฟลเดอร์เก็บคลิป")
    args = ap.parse_args()
    out_dir = Path(args.out)

    jobs = []
    if args.csv:
        with open(args.csv, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                jobs.append((r["url"], r["start"], r["end"], r.get("note", "")))
    elif args.url and args.range and "-" in args.range:
        start, end = args.range.split("-", 1)
        jobs.append((args.url, start, end, args.note))
    else:
        ap.error("ใส่ลิงก์ + ช่วงเวลา หรือใช้ --csv")

    ok = 0
    for url, start, end, note in jobs:
        try:
            row = fetch(url, start, end, note, out_dir)
            log_credit(row, out_dir)
            ok += 1
            print(f"✓ {row['channel']} | {start}-{end} -> {row['file']}")
        except Exception as e:  # ทำคลิปต่อไปแม้บางลิงก์พลาด
            print(f"✗ {url} ({start}-{end}): {e}", file=sys.stderr)
    print(f"เสร็จ {ok}/{len(jobs)} คลิป  เครดิต: credits.csv / credits.txt")


if __name__ == "__main__":
    main()
