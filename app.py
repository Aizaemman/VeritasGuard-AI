
import asyncio
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone

import streamlit as st

from agent import analyze_claim, extract_claims
from mcp_client import search_claim_evidence
from database import (
    test_connection,
    save_report as mongo_save_report,
    load_reports as mongo_load_reports,
)


# ============================================================
# 1. PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="VeritasGuard AI",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# 2. PREMIUM DASHBOARD DESIGN
# ============================================================

# IMPORTANT:
# HTML is rendered ONLY with st.html().
# No duplicate st.markdown() header exists.

st.html("""
<style>
.block-container {
    max-width: 1250px;
    padding-top: 2rem;
    padding-bottom: 3rem;
}

.vg-header {
    background: linear-gradient(120deg, #071B46, #1232E5);
    border-radius: 20px;
    padding: 38px;
    margin-bottom: 25px;
    box-shadow: 0 12px 35px rgba(18,50,229,0.15);
}

.vg-eyebrow {
    color: #B9C9FF;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 2px;
    margin-bottom: 12px;
}

.vg-title {
    color: white !important;
    font-size: 42px;
    font-weight: 800;
    line-height: 1.2;
}

.vg-subtitle {
    color: #DCE5FF;
    font-size: 15px;
    margin-top: 14px;
    line-height: 1.7;
}

.vg-tag {
    display: inline-block;
    background: #F36D51;
    color: white;
    padding: 8px 15px;
    border-radius: 30px;
    font-size: 11px;
    font-weight: 700;
    margin-top: 20px;
}

div[data-testid="stTextArea"] textarea {
    border: 1px solid #DCE3F0;
    border-radius: 12px;
    background: white;
    color: #071B46;
    font-size: 15px;
}

div[data-testid="stTextArea"] textarea:focus {
    border-color: #1232E5;
}
</style>
""")

st.html("""
<div class="vg-header">
  <div class="vg-eyebrow">
    AGENTIKA 2.0 / AI INTELLIGENCE
  </div>
  <div class="vg-title">
    🛡️ VERITASGUARD AI
  </div>
  <div class="vg-subtitle">
    Autonomous Evidence Intelligence &amp;
    Human-Verified Misinformation Detection
  </div>
  <div class="vg-tag">
    HUMAN + AI : BETTER TOGETHER
  </div>
</div>
""")


# ============================================================
# 3. CONFIGURATION
# ============================================================

VERDICT_OPTIONS = [
    "Supported",
    "Contradicted",
    "Misleading",
    "Unverified",
]

REPORTS_DIR = Path(__file__).resolve().parent / "reports_data"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def create_report_id():
    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%d_%H%M%S"
    )
    return f"{timestamp}_{uuid.uuid4().hex[:8]}"


def create_report(report_id, report_type, claims, saved_at=None):
    return {
        "report_id": report_id,
        "project": "VeritasGuard AI",
        "report_type": report_type,
        "saved_at": saved_at or utc_now(),
        "total_claims": len(claims),
        "approved_claims": len(claims),
        "overall_review_status": "Human Approved",
        "claims": claims,
    }


# ============================================================
# 4. SESSION STATE
# ============================================================

defaults = {
    "claim_input": "",
    "extracted_claims": [],
    "extracted_from": "",
    "multi_results": [],
    "multi_approvals": {},
    "multi_report_id": None,
    "multi_saved_at": None,
    "multi_saved": False,
    "analysis": None,
    "sources": [],
    "reviewed": False,
    "final_report": None,
    "single_saved": False,
    "single_save_error": None,
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# 5. MONGODB FUNCTIONS
# ============================================================

def save_report(report):
    if not isinstance(report, dict):
        raise ValueError("Invalid report.")

    if not report.get("report_id"):
        raise ValueError("Missing report ID.")

    if report.get("overall_review_status") != "Human Approved":
        raise ValueError("Report is not human approved.")

    claims = report.get("claims", [])

    if not claims or any(
        not isinstance(item, dict)
        or item.get("review_status") != "Human Approved"
        for item in claims
    ):
        raise ValueError("All claims must be approved.")

    success = mongo_save_report(report)

    if not success:
        raise RuntimeError("MongoDB failed to save report.")

    return True


def load_reports():
    documents = mongo_load_reports()
    reports = []

    for document in documents:
        if not isinstance(document, dict):
            continue

        if document.get("overall_review_status") != "Human Approved":
            continue

        reports.append(document)

    return sorted(
        reports,
        key=lambda item: str(item.get("saved_at", "")),
        reverse=True,
    )


def get_analytics(reports):
    stats = {
        "investigations": len(reports),
        "approved_claims": 0,
        "Supported": 0,
        "Contradicted": 0,
        "Misleading": 0,
        "Unverified": 0,
    }

    for report in reports:
        for claim in report.get("claims", []):
            if not isinstance(claim, dict):
                continue

            if claim.get("review_status") != "Human Approved":
                continue

            stats["approved_claims"] += 1

            verdict = claim.get("human_verdict", "Unverified")

            if verdict in VERDICT_OPTIONS:
                stats[verdict] += 1

    return stats


def migrate_old_reports():
    if not REPORTS_DIR.exists():
        return 0, 0

    imported = 0
    skipped = 0

    for path in REPORTS_DIR.glob("*.json"):
        try:
            report = json.loads(
                path.read_text(encoding="utf-8")
            )

            if not isinstance(report, dict):
                skipped += 1
                continue

            save_report(report)
            imported += 1

        except Exception:
            skipped += 1

    return imported, skipped


# ============================================================
# 6. MCP + AI FUNCTIONS
# ============================================================

def retrieve_evidence(claim_text):
    result = asyncio.run(
        search_claim_evidence(claim_text)
    )

    if isinstance(result, list):
        if not result:
            raise ValueError("MCP returned no response.")
        evidence = result[0]
    else:
        evidence = result

    if isinstance(evidence, str):
        evidence = json.loads(evidence)

    if not isinstance(evidence, dict):
        raise ValueError("Invalid MCP response.")

    if evidence.get("error"):
        raise ValueError(str(evidence["error"]))

    sources = evidence.get("sources", [])

    if not isinstance(sources, list):
        raise ValueError("Invalid evidence sources.")

    return sources


def investigate_claim(claim_text):
    sources = retrieve_evidence(claim_text)

    if not sources:
        return {
            "claim": claim_text,
            "verdict": "Unverified",
            "confidence": "Low",
            "explanation": (
                "No relevant evidence was retrieved. "
                "This does not prove the claim is false."
            ),
            "sources": [],
            "source_urls": [],
            "error": None,
        }

    analysis = analyze_claim(claim_text, sources)

    if not isinstance(analysis, dict):
        raise ValueError("Invalid AI analysis.")

    if analysis.get("error"):
        raise ValueError(str(analysis["error"]))

    urls = [
        source.get("url", "")
        for source in sources
        if isinstance(source, dict)
        and str(source.get("url", "")).startswith(
            ("https://", "http://")
        )
    ]

    return {
        "claim": claim_text,
        "verdict": analysis.get("verdict", "Unverified"),
        "confidence": analysis.get("confidence", "Low"),
        "explanation": analysis.get("explanation", ""),
        "sources": sources,
        "source_urls": urls,
        "error": None,
    }


def display_sources(sources):
    if not sources:
        st.info("No evidence sources available.")
        return

    for index, source in enumerate(sources, 1):
        if not isinstance(source, dict):
            continue

        title = source.get("title", "Untitled")

        with st.expander(f"Source {index}: {title}"):
            st.write(source.get("content", ""))

            url = str(source.get("url", ""))

            if url.startswith(("https://", "http://")):
                st.link_button("Open Source", url)


def reset_multi_review():
    st.session_state.multi_results = []
    st.session_state.multi_approvals = {}
    st.session_state.multi_report_id = None
    st.session_state.multi_saved_at = None
    st.session_state.multi_saved = False

    for key in list(st.session_state.keys()):
        if key.startswith(("multi_verdict_", "multi_notes_")):
            del st.session_state[key]


def build_approved_claim(
    result,
    human_verdict,
    reviewer_notes,
    claim_number=None,
):
    approved = {
        "claim": result["claim"],
        "ai_verdict": result["verdict"],
        "human_verdict": human_verdict,
        "confidence": result["confidence"],
        "explanation": result["explanation"],
        "reviewer_notes": reviewer_notes,
        "source_urls": result["source_urls"],
        "review_status": "Human Approved",
        "approved_at": utc_now(),
    }

    if claim_number is not None:
        approved["claim_number"] = claim_number

    return approved


# ============================================================
# 7. SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("## 🛡️ VERITASGUARD")
    st.caption("Intelligence Control Center")

    st.divider()

    st.markdown("### ⚡ System Modules")
    st.markdown("🔍 **Claim Investigation**")
    st.markdown("🧠 **AI Evidence Analysis**")
    st.markdown("🌐 **MCP Source Retrieval**")
    st.markdown("👤 **Human Review Console**")
    st.markdown("📁 **Investigation History**")
    st.markdown("📊 **Analytics Dashboard**")

    st.divider()
    st.markdown("### 🗄️ Database")

    if st.button("🔄 Check MongoDB Connection"):
        if test_connection():
            st.success("MongoDB connected!")
        else:
            st.error("MongoDB connection failed.")


# ============================================================
# 8. DATABASE STATUS
# ============================================================

@st.cache_data(ttl=30, show_spinner=False)
def database_is_connected():
    return test_connection()


mongo_connected = database_is_connected()

if mongo_connected:
    st.success("🟢 MongoDB Connected — VeritasGuardDB")
else:
    st.error(
        "🔴 MongoDB disconnected. "
        "Start MongoDB Server to save investigations."
    )

st.info(
    "🤝 AI investigates and recommends. "
    "Human reviewers verify and approve the final verdict."
)


# ============================================================
# 9. ANALYTICS DASHBOARD
# ============================================================

st.markdown("### 📊 Investigation Analytics")

saved_reports = load_reports() if mongo_connected else []
stats = get_analytics(saved_reports)

col1, col2, col3 = st.columns(3)

with col1:
    st.metric(
        "Total Investigations",
        stats["investigations"],
    )

with col2:
    st.metric(
        "Approved Claims",
        stats["approved_claims"],
    )

with col3:
    st.metric(
        "Contradicted Claims",
        stats["Contradicted"],
    )

with st.expander("📈 View Verdict Statistics"):
    verdict_data = {
        verdict: stats[verdict]
        for verdict in VERDICT_OPTIONS
    }

    st.bar_chart(verdict_data, horizontal=True)

    st.caption(
        "Statistics use final human verdicts "
        "from approved MongoDB reports."
    )


# ============================================================
# 10. INVESTIGATION HISTORY
# ============================================================

with st.expander("📁 Investigation History & Previous Reports"):
    if not mongo_connected:
        st.warning("MongoDB connection required.")

    elif not saved_reports:
        st.info("No approved investigations saved yet.")

    else:
        st.caption(
            f"{len(saved_reports)} saved investigation(s)"
        )

        for index, report in enumerate(saved_reports, 1):
            report_type = report.get(
                "report_type",
                "Investigation",
            )
            claims = report.get("claims", [])

            with st.expander(
                f"Report {index}: {report_type} "
                f"— {len(claims)} claim(s)"
            ):
                st.write(
                    "**Saved At:**",
                    report.get("saved_at", "Unknown"),
                )

                st.write("**Status:** Human Approved")

                for claim_item in claims:
                    st.write(
                        "**Claim:**",
                        claim_item.get("claim", ""),
                    )
                    st.write(
                        "**Human Verdict:**",
                        claim_item.get(
                            "human_verdict",
                            "Unverified",
                        ),
                    )

                st.download_button(
                    "📥 Download Previous Report",
                    data=json.dumps(
                        report,
                        indent=2,
                        ensure_ascii=False,
                        default=str,
                    ),
                    file_name=(
                        f"{report.get('report_id', 'report')}.json"
                    ),
                    mime="application/json",
                    key=f"history_download_{index}",
                )


# ============================================================
# 11. IMPORT PREVIOUS JSON REPORTS
# ============================================================

with st.expander("📦 Import Old JSON Reports to MongoDB"):
    st.caption(
        "Import previously saved reports_data JSON files. "
        "Original files will not be deleted."
    )

    if st.button(
        "📥 Import Existing Reports",
        disabled=not mongo_connected,
    ):
        with st.spinner("Importing reports..."):
            imported, skipped = migrate_old_reports()

        st.success(
            f"Import completed: {imported} processed, "
            f"{skipped} skipped."
        )

        st.rerun()


# ============================================================
# 12. INVESTIGATION WORKSPACE
# ============================================================

st.divider()

# No HTML header is repeated here.

st.subheader("🔍 Intelligence Investigation")

st.caption(
    "Submit a suspicious headline or factual claim "
    "to begin AI-powered evidence verification."
)

claim = st.text_area(
    "News or factual claim",
    placeholder=(
        "Paste a suspicious headline or full article here...\n\n"
        "Example: The Great Wall of China is visible from the Moon."
    ),
    height=180,
    label_visibility="collapsed",
    key="claim_input",
)

st.caption(
    "🔒 Evidence is retrieved through MCP tools. "
    "All AI assessments require human verification."
)


# ============================================================
# 13. AUTOMATIC CLAIM EXTRACTION
# ============================================================

if st.button(
    "✨ Auto Extract Claims",
    key="extract_claims_btn",
):
    if not claim.strip():
        st.warning("Please paste a news article first.")

    else:
        st.session_state.extracted_claims = []
        st.session_state.extracted_from = ""

        reset_multi_review()

        with st.spinner("AI is extracting factual claims..."):
            try:
                extracted = extract_claims(claim.strip())

                if not isinstance(extracted, list):
                    raise ValueError(
                        "AI returned an invalid claims list."
                    )

                clean_claims = [
                    item.strip()
                    for item in extracted
                    if isinstance(item, str) and item.strip()
                ][:3]

                st.session_state.extracted_claims = clean_claims
                st.session_state.extracted_from = claim.strip()

                if clean_claims:
                    st.success(
                        f"{len(clean_claims)} claims extracted!"
                    )
                else:
                    st.warning(
                        "No verifiable factual claims found."
                    )

            except Exception as error:
                st.error(
                    f"Claim extraction failed: {error}"
                )


# ============================================================
# 14. EXTRACTED CLAIMS
# ============================================================

article_changed = (
    bool(st.session_state.extracted_claims)
    and claim.strip() != st.session_state.extracted_from
)

if article_changed:
    st.warning(
        "Article changed since extraction. "
        "Extract claims again before investigating."
    )


if st.session_state.extracted_claims:
    st.markdown("### 🧠 AI-Extracted Claims")

    for index, item in enumerate(
        st.session_state.extracted_claims,
        1,
    ):
        st.markdown(f"**Claim {index}:** {item}")

    if st.button(
        "🚀 Investigate All Extracted Claims",
        disabled=article_changed,
        key="investigate_all_btn",
    ):
        reset_multi_review()

        claims_to_check = st.session_state.extracted_claims[:3]
        total_claims = len(claims_to_check)

        progress_bar = st.progress(0)

        with st.status(
            "🚀 Multi-Claim Investigation in Progress",
            expanded=True,
        ) as multi_status:

            for index, current_claim in enumerate(
                claims_to_check,
                1,
            ):
                st.write(
                    f"🔍 Investigating claim "
                    f"{index} of {total_claims}"
                )

                try:
                    result = investigate_claim(current_claim)

                    st.session_state.multi_results.append(result)

                    st.write(
                        f"✅ Claim {index} investigated."
                    )

                except Exception as error:
                    st.session_state.multi_results.append({
                        "claim": current_claim,
                        "verdict": "Unverified",
                        "confidence": "Low",
                        "explanation": (
                            "Investigation could not be completed."
                        ),
                        "sources": [],
                        "source_urls": [],
                        "error": str(error),
                    })

                    st.warning(
                        f"Claim {index} failed: {error}"
                    )

                progress_bar.progress(
                    index / total_claims
                )

            multi_status.update(
                label=(
                    "✅ Multi-Claim Investigation Finished "
                    "— Human Review Required"
                ),
                state="complete",
                expanded=False,
            )


# ============================================================
# 15. MULTI-CLAIM HUMAN REVIEW
# ============================================================

if st.session_state.multi_results:
    st.divider()
    st.subheader("📊 Multi-Claim Investigation Results")

    results = st.session_state.multi_results
    total = len(results)
    approved_count = len(st.session_state.multi_approvals)

    st.progress(approved_count / total)

    st.caption(
        f"Human Review Progress: "
        f"{approved_count} of {total} claims approved."
    )

    st.info(
        "AI verdicts are preliminary. "
        "Every claim requires human approval."
    )

    for index, result in enumerate(results, 1):
        approval_key = index - 1

        with st.container(border=True):
            st.markdown(f"### 🔍 Claim {index}")
            st.write(result["claim"])

            col1, col2 = st.columns(2)

            with col1:
                st.metric(
                    "AI Verdict",
                    result["verdict"],
                )

            with col2:
                st.metric(
                    "AI Confidence",
                    result["confidence"],
                )

            if result.get("error"):
                st.error(
                    "Investigation failed: "
                    + result["error"]
                )

                st.warning(
                    "Resolve this error before approving."
                )
                continue

            st.write("**🤖 AI Explanation:**")
            st.write(result["explanation"])

            st.markdown("**🔗 Evidence Sources**")
            display_sources(result["sources"])

            st.divider()
            st.markdown("#### 👤 Human Review")

            existing_approval = (
                st.session_state.multi_approvals.get(
                    approval_key
                )
            )

            if existing_approval:
                st.success("✅ Human review approved.")

                st.write(
                    "**Final Human Verdict:**",
                    existing_approval["human_verdict"],
                )

                if existing_approval["reviewer_notes"]:
                    st.write(
                        "**Reviewer Notes:**",
                        existing_approval["reviewer_notes"],
                    )

                if st.button(
                    "✏️ Edit This Review",
                    key=f"edit_review_{index}",
                ):
                    del st.session_state.multi_approvals[
                        approval_key
                    ]

                    st.session_state.multi_report_id = None
                    st.session_state.multi_saved_at = None
                    st.session_state.multi_saved = False

                    st.rerun()

            else:
                ai_verdict = result.get(
                    "verdict",
                    "Unverified",
                )

                default_index = (
                    VERDICT_OPTIONS.index(ai_verdict)
                    if ai_verdict in VERDICT_OPTIONS
                    else 3
                )

                with st.form(
                    key=f"multi_review_form_{index}"
                ):
                    human_verdict = st.selectbox(
                        "Final Human Verdict",
                        VERDICT_OPTIONS,
                        index=default_index,
                        key=f"multi_verdict_{index}",
                    )

                    reviewer_notes = st.text_area(
                        "Reviewer Notes",
                        placeholder=(
                            "Explain your decision or corrections..."
                        ),
                        key=f"multi_notes_{index}",
                    )

                    approve_clicked = st.form_submit_button(
                        "✅ Approve Claim",
                        type="primary",
                    )

                if approve_clicked:
                    approved_claim = build_approved_claim(
                        result,
                        human_verdict,
                        reviewer_notes,
                        claim_number=index,
                    )

                    st.session_state.multi_approvals[
                        approval_key
                    ] = approved_claim

                    st.session_state.multi_report_id = None
                    st.session_state.multi_saved_at = None
                    st.session_state.multi_saved = False

                    st.rerun()


    # ========================================================
    # 16. COMBINED REPORT
    # ========================================================

    st.divider()
    st.subheader("📋 Combined Investigation Report")

    approved_count = len(
        st.session_state.multi_approvals
    )

    all_approved = (
        approved_count == total
        and all(
            not result.get("error")
            for result in results
        )
    )

    if all_approved:
        st.success(
            "🎉 All claims have been human reviewed "
            "and approved!"
        )

        approved_claims = [
            st.session_state.multi_approvals[index]
            for index in range(total)
        ]

        if not st.session_state.multi_report_id:
            st.session_state.multi_report_id = (
                create_report_id()
            )

        if not st.session_state.multi_saved_at:
            st.session_state.multi_saved_at = utc_now()

        combined_report = create_report(
            report_id=st.session_state.multi_report_id,
            report_type=(
                "Multi-Claim Human-Verified Investigation"
            ),
            claims=approved_claims,
            saved_at=st.session_state.multi_saved_at,
        )

        if not st.session_state.multi_saved:
            if mongo_connected:
                try:
                    save_report(combined_report)

                    st.session_state.multi_saved = True

                except Exception as error:
                    st.error(
                        f"MongoDB save failed: {error}"
                    )
            else:
                st.error(
                    "MongoDB disconnected. "
                    "Combined report not saved."
                )

        if st.session_state.multi_saved:
            st.success(
                "🗄️ Combined report saved to MongoDB!"
            )
        elif mongo_connected:
            if st.button("🔄 Retry Saving Combined Report"):
                try:
                    save_report(combined_report)
                    st.session_state.multi_saved = True
                    st.rerun()
                except Exception as error:
                    st.error(str(error))

        st.json(combined_report)

        st.download_button(
            "📥 Download Combined Approved Report",
            data=json.dumps(
                combined_report,
                indent=2,
                ensure_ascii=False,
            ),
            file_name="veritasguard_combined_report.json",
            mime="application/json",
            key="download_combined_report",
        )

    else:
        remaining = total - approved_count

        st.warning(
            f"{remaining} claim(s) still require "
            "human approval."
        )


# ============================================================
# 17. INDIVIDUAL CLAIM INVESTIGATION
# ============================================================

st.divider()
st.subheader("🔎 Individual Claim Investigation")

st.caption(
    "Investigate the text in the input box "
    "as a single claim."
)

if st.button(
    "🔍 Analyze Claim",
    type="primary",
    key="single_analyze_btn",
):
    if not claim.strip():
        st.warning("Please enter a claim.")

    else:
        st.session_state.analysis = None
        st.session_state.sources = []
        st.session_state.reviewed = False
        st.session_state.final_report = None
        st.session_state.single_saved = False
        st.session_state.single_save_error = None

        for key in (
            "single_final_verdict",
            "single_reviewer_notes",
        ):
            st.session_state.pop(key, None)

        with st.status(
            "🔍 AI Investigation in Progress",
            expanded=True,
        ) as investigation_status:

            try:
                st.write(
                    "🌐 Stage 1: Searching evidence "
                    "through MCP + Tavily..."
                )

                sources = retrieve_evidence(claim.strip())

                if not sources:
                    st.warning(
                        "No evidence found. "
                        "The claim cannot be verified."
                    )

                else:
                    st.write(
                        "🧠 Stage 2: Evaluating evidence "
                        "with Groq AI..."
                    )

                    analysis = analyze_claim(
                        claim.strip(),
                        sources,
                    )

                    if not isinstance(analysis, dict):
                        raise ValueError(
                            "Invalid AI analysis response."
                        )

                    if analysis.get("error"):
                        raise ValueError(
                            str(analysis["error"])
                        )

                    st.session_state.analysis = analysis
                    st.session_state.sources = sources

                    investigation_status.update(
                        label=(
                            "✅ AI Investigation Complete "
                            "— Awaiting Human Review"
                        ),
                        state="complete",
                        expanded=False,
                    )

            except Exception as error:
                st.error(
                    f"Analysis failed: {error}"
                )


# ============================================================
# 18. SINGLE-CLAIM RESULTS
# ============================================================

if st.session_state.analysis:
    analysis = st.session_state.analysis

    st.divider()
    st.subheader("🤖 AI Fact-Check Assessment")

    col1, col2 = st.columns(2)

    with col1:
        st.metric(
            "AI Verdict",
            analysis.get("verdict", "Unverified"),
        )

    with col2:
        st.metric(
            "AI Confidence",
            analysis.get("confidence", "Low"),
        )

    st.write("**Explanation:**")
    st.write(
        analysis.get("explanation", "")
    )

    st.subheader("🔗 Retrieved Evidence")
    display_sources(st.session_state.sources)

    st.divider()
    st.subheader("👤 Human-in-the-Loop Review")

    st.write(
        "Review the evidence, correct the AI verdict "
        "if necessary, and approve the final assessment."
    )

    ai_verdict = analysis.get(
        "verdict",
        "Unverified",
    )

    default_index = (
        VERDICT_OPTIONS.index(ai_verdict)
        if ai_verdict in VERDICT_OPTIONS
        else 3
    )

    if st.session_state.reviewed:
        st.success(
            "Assessment approved by human reviewer!"
        )

        if st.session_state.single_saved:
            st.success(
                "🗄️ Report saved to MongoDB!"
            )

        else:
            st.error(
                "MongoDB save failed: "
                + str(
                    st.session_state.single_save_error
                    or "Report not saved."
                )
            )

            if st.button("🔄 Retry Saving Report"):
                try:
                    save_report(
                        st.session_state.final_report
                    )
                    st.session_state.single_saved = True
                    st.session_state.single_save_error = None
                    st.rerun()

                except Exception as error:
                    st.error(str(error))

        st.json(
            st.session_state.final_report
        )

        st.download_button(
            "📥 Download Approved Report",
            data=json.dumps(
                st.session_state.final_report,
                indent=2,
                ensure_ascii=False,
            ),
            file_name="veritasguard_report.json",
            mime="application/json",
            key="single_download_report",
        )

        if st.button(
            "✏️ Edit Single-Claim Review",
            key="edit_single_review",
        ):
            st.session_state.reviewed = False
            st.session_state.final_report = None
            st.session_state.single_saved = False
            st.session_state.single_save_error = None

            st.rerun()

    else:
        with st.form("single_review_form"):
            final_verdict = st.selectbox(
                "Final Human Verdict",
                VERDICT_OPTIONS,
                index=default_index,
                key="single_final_verdict",
            )

            reviewer_notes = st.text_area(
                "Reviewer Notes",
                placeholder=(
                    "Explain your decision or corrections..."
                ),
                key="single_reviewer_notes",
            )

            approve_single = st.form_submit_button(
                "✅ Approve Final Assessment",
                type="primary",
            )

        if approve_single:
            source_urls = [
                source.get("url", "")
                for source in st.session_state.sources
                if isinstance(source, dict)
                and str(
                    source.get("url", "")
                ).startswith(("https://", "http://"))
            ]

            result = {
                "claim": analysis.get(
                    "claim",
                    claim.strip(),
                ),
                "verdict": ai_verdict,
                "confidence": analysis.get(
                    "confidence",
                    "Low",
                ),
                "explanation": analysis.get(
                    "explanation",
                    "",
                ),
                "source_urls": source_urls,
            }

            approved_claim = build_approved_claim(
                result,
                final_verdict,
                reviewer_notes,
            )

            final_report = create_report(
                report_id=create_report_id(),
                report_type=(
                    "Single-Claim Human-Verified Investigation"
                ),
                claims=[approved_claim],
            )

            st.session_state.final_report = final_report
            st.session_state.reviewed = True
            st.session_state.single_saved = False

            if mongo_connected:
                try:
                    save_report(final_report)
                    st.session_state.single_saved = True
                    st.session_state.single_save_error = None

                except Exception as error:
                    st.session_state.single_save_error = (
                        str(error)
                    )

            else:
                st.session_state.single_save_error = (
                    "MongoDB is disconnected."
                )

            st.rerun()
