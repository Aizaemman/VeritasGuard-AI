
import os
from datetime import datetime, timezone

from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# MongoDB Connection
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb://localhost:27017/"
)

client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=5000
)

db = client["VeritasGuardDB"]
investigations = db["investigations"]


# 1. Test MongoDB Connection
def test_connection():
    try:
        client.admin.command("ping")
        print("MongoDB connected successfully!")
        return True
    except Exception as error:
        print("MongoDB connection failed:", error)
        return False


# 2. Save Investigation Report
def save_report(report):
    try:
        report = report.copy()

        # Use report_id to prevent duplicate reports
        report_id = report.get("report_id")

        if not report_id:
            raise ValueError("Report must contain report_id")

        report.setdefault(
            "saved_at",
            datetime.now(timezone.utc).isoformat()
        )

        investigations.update_one(
            {"report_id": report_id},
            {"$set": report},
            upsert=True
        )

        print("Report saved successfully!")
        return True

    except Exception as error:
        print("Error saving report:", error)
        return False


# 3. Load Investigation History
def load_reports():
    try:
        reports = list(
            investigations.find(
                {},
                {"_id": 0}
            ).sort("saved_at", -1)
        )

        return reports

    except Exception as error:
        print("Error loading reports:", error)
        return []


# 4. Calculate Analytics
def get_analytics():
    reports = load_reports()

    total_investigations = len(reports)
    approved_claims = 0
    contradicted_claims = 0
    verdict_counts = {}

    for report in reports:
        for claim in report.get("claims", []):
            if claim.get("review_status") == "Human Approved":
                approved_claims += 1

            verdict = str(
                claim.get("ai_verdict", "Unknown")
            )

            verdict_counts[verdict] = (
                verdict_counts.get(verdict, 0) + 1
            )

            if "contradict" in verdict.lower():
                contradicted_claims += 1

    return {
        "total_investigations": total_investigations,
        "approved_claims": approved_claims,
        "contradicted_claims": contradicted_claims,
        "verdict_counts": verdict_counts
    }


if __name__ == "__main__":
    test_connection()
