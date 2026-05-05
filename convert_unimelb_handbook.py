import json
from datetime import date

with open("data/unimelb_subjects_2026.json", "r", encoding="utf-8") as f:
    subjects = json.load(f)

converted = []

for subject in subjects:
    subject_code = subject["subject_code"]

    text = f"""
Subject code: {subject_code}
Year: {subject.get("year", "")}

Overview:
{subject.get("overview", "")}

Eligibility and requirements:
{subject.get("eligibility_and_requirements", "")}

Assessment:
{subject.get("assessment", "")}

Dates and times:
{subject.get("dates_and_times", "")}

Further information:
{subject.get("further_information", "")}
""".strip()

    converted.append({
        "questions": [
            subject_code,
            f"What is {subject_code} about?",
            f"What are the requirements for {subject_code}?",
            f"What are the assessments for {subject_code}?",
            f"When is {subject_code} offered?"
        ],
        "text": text,
        "source": "handbook.unimelb.edu.au",
        "author": None,
        "post_date": subject.get("year"),
        "language": "english",
        "created_at": str(date.today()),
        "tags": [
            "unimelb",
            "subject",
            subject_code
        ],
        "link": subject.get("base_url")
    })

with open("data/unimelb_subjects_demo_format.json", "w", encoding="utf-8") as f:
    json.dump(converted, f, ensure_ascii=False, indent=2)
