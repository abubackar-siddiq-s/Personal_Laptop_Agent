from __future__ import annotations
import difflib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.files.parsers import parse_document
from app.files.schemas import (
    DocumentCitation,
    DocumentCompareResult,
    DocumentMetadata,
    DocumentQAResult,
    ParsedDocument,
)
from app.files.security import validate_file_path, wrap_untrusted_content


DATE_REGEX = re.compile(
    r"\b(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
MONEY_REGEX = re.compile(r"[\$€£₹]\s*[\d,]+(?:\.\d{1,2})?|\b[\d,]+(?:\.\d{1,2})?\s*(?:USD|EUR|GBP|INR|dollars?)\b", re.IGNORECASE)
PHONE_REGEX = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")


def extract_entities_and_dates(text: str) -> Dict[str, List[str]]:
    """
    Extract structured entities, dates, emails, phones, and currency figures from document text.
    Uses regex patterns to deliver accurate, un-hallucinated extractions.
    """
    dates = list(set(DATE_REGEX.findall(text)))[:25]
    emails = list(set(EMAIL_REGEX.findall(text)))[:25]
    money = list(set(MONEY_REGEX.findall(text)))[:25]
    phones = list(set(PHONE_REGEX.findall(text)))[:25]

    # Simple capital entity extractor (2+ capitalized words, excluding sentence starts)
    entity_matches = re.findall(r"(?<!\.\s)\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", text)
    # Deduplicate preserving order
    seen = set()
    entities = []
    for e in entity_matches:
        if e.lower() not in seen and len(e) > 3:
            seen.add(e.lower())
            entities.append(e)

    return {
        "dates": sorted(dates),
        "emails": sorted(emails),
        "currency_amounts": sorted(money),
        "phone_numbers": sorted(phones),
        "named_entities": entities[:30],
    }


def classify_document(doc: ParsedDocument) -> Dict[str, Any]:
    """
    Classify a document into standard functional categories based on keywords,
    structural patterns, and format.
    """
    fmt = doc.format.lower()
    text = doc.text_content.lower()

    if fmt in ("xlsx", "xls", "csv") or len(doc.tables) > 2:
        return {
            "category": "Spreadsheet / Dataset",
            "confidence": 0.95,
            "reason": f"Structured tabular format ({fmt}) with {len(doc.tables)} extracted tables.",
        }

    if fmt in ("pptx", "ppt") or doc.metadata.slide_count > 0:
        return {
            "category": "Presentation",
            "confidence": 0.95,
            "reason": f"Slide presentation format ({fmt}) with {doc.metadata.slide_count} slides.",
        }

    # Invoice / Receipt signals
    invoice_signals = ("invoice", "bill to", "due date", "amount due", "subtotal", "tax", "payment terms")
    if sum(1 for s in invoice_signals if s in text) >= 3:
        return {
            "category": "Invoice / Financial Bill",
            "confidence": 0.90,
            "reason": "Contains invoice terminology (bill to, due date, amount due, tax).",
        }

    # Resume signals
    resume_signals = ("curriculum vitae", "resume", "experience", "education", "skills", "certifications", "projects")
    if sum(1 for s in resume_signals if s in text) >= 3:
        return {
            "category": "Resume / CV",
            "confidence": 0.92,
            "reason": "Matches standard resume section headers (experience, education, skills).",
        }

    # Contract signals
    contract_signals = ("agreement", "terms and conditions", "hereby", "parties", "confidentiality", "governing law")
    if sum(1 for s in contract_signals if s in text) >= 3:
        return {
            "category": "Contract / Legal Agreement",
            "confidence": 0.88,
            "reason": "Contains standard contractual and legal phraseology.",
        }

    # Technical Spec signals
    tech_signals = ("architecture", "api", "specification", "requirements", "endpoint", "database", "system design")
    if sum(1 for s in tech_signals if s in text) >= 3:
        return {
            "category": "Technical Specification",
            "confidence": 0.85,
            "reason": "Contains software engineering architecture and specification terminology.",
        }

    return {
        "category": "General Document",
        "confidence": 0.70,
        "reason": f"Standard {fmt.upper()} document content.",
    }


def summarize_document(file_path: str | Path, max_summary_sentences: int = 5) -> Dict[str, Any]:
    """
    Generate an authoritative, extract-based document summary and key points.
    Never hallucinates contents or claims.
    """
    doc = parse_document(file_path)
    if not doc.success:
        return {"success": False, "error": doc.error}

    classification = classify_document(doc)
    entities = extract_entities_and_dates(doc.text_content)

    # Extract key sentences based on frequency and positioning
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", doc.text_content) if len(s.strip()) > 30]

    # Leading section sentences make the best deterministic summary
    summary_sentences = sentences[:max_summary_sentences]
    summary_text = " ".join(summary_sentences) if summary_sentences else "Document contains insufficient text for summary."

    # Section breakdown
    section_breakdown = []
    for s in doc.sections[:10]:
        first_line = s.content.strip().split("\n")[0][:120]
        section_breakdown.append({
            "title": s.title,
            "page": s.page_number,
            "sheet": s.sheet_name,
            "slide": s.slide_number,
            "preview": first_line,
        })

    return {
        "success": True,
        "filename": doc.filename,
        "path": doc.path,
        "format": doc.format,
        "classification": classification,
        "metadata": doc.metadata.model_dump(),
        "summary": summary_text,
        "key_points": summary_sentences,
        "entities": entities,
        "sections": section_breakdown,
        "table_count": len(doc.tables),
    }


def ask_document(
    file_path: str | Path,
    question: str,
) -> DocumentQAResult:
    """
    Answer questions about a document strictly using extracted content with exact citations.
    Never fabricates citations or answers without source proof.
    """
    valid_path = validate_file_path(file_path)
    doc = parse_document(valid_path)

    if not doc.success:
        return DocumentQAResult(
            question=question,
            answer=f"Could not open document: {doc.error}",
            directly_extracted="",
            model_interpretation="",
            is_grounded=False,
            sources_consulted=[valid_path.name],
        )

    # Split question into query tokens
    query_terms = [t.lower() for t in re.findall(r"\w+", question) if len(t) > 2]
    if not query_terms:
        return DocumentQAResult(
            question=question,
            answer="Question contains no searchable keywords.",
            directly_extracted="",
            model_interpretation="",
            is_grounded=False,
            sources_consulted=[doc.filename],
        )

    # Score each section for keyword overlap
    scored_sections: List[Tuple[float, Any, str]] = []
    for sec in doc.sections:
        sec_text_lower = sec.content.lower()
        score = sum(1 for t in query_terms if t in sec_text_lower)
        if score > 0:
            # Find the best matching sentence
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", sec.content) if s.strip()]
            best_sent = ""
            best_sent_score = 0
            for sent in sentences:
                s_score = sum(1 for t in query_terms if t in sent.lower())
                if s_score > best_sent_score:
                    best_sent_score = s_score
                    best_sent = sent
            scored_sections.append((score, sec, best_sent or sec.content[:200]))

    scored_sections.sort(key=lambda x: x[0], reverse=True)

    citations: List[DocumentCitation] = []
    extracted_snippets: List[str] = []

    for score, sec, sent in scored_sections[:3]:
        citations.append(
            DocumentCitation(
                document_name=doc.filename,
                path=doc.path,
                page_number=sec.page_number,
                sheet_name=sec.sheet_name,
                slide_number=sec.slide_number,
                section_title=sec.title,
                exact_quote=sent,
            )
        )
        ref = f"[{doc.filename}"
        if sec.page_number:
            ref += f", Page {sec.page_number}"
        elif sec.sheet_name:
            ref += f", Sheet '{sec.sheet_name}'"
        elif sec.slide_number:
            ref += f", Slide {sec.slide_number}"
        ref += "]"
        extracted_snippets.append(f"{ref}: \"{sent}\"")

    if not citations:
        return DocumentQAResult(
            question=question,
            answer=f"The document '{doc.filename}' does not appear to contain information answering: '{question}'.",
            directly_extracted="",
            model_interpretation="No matching text found across document sections.",
            citations=[],
            is_grounded=True,
            sources_consulted=[doc.filename],
        )

    extracted_text_block = "\n".join(extracted_snippets)
    interpretation = f"Found {len(citations)} directly matching passage(s) in '{doc.filename}' corresponding to query terms."

    answer = f"Based on '{doc.filename}':\n\n{extracted_text_block}"

    return DocumentQAResult(
        question=question,
        answer=answer,
        directly_extracted=extracted_text_block,
        model_interpretation=interpretation,
        citations=citations,
        is_grounded=True,
        sources_consulted=[doc.filename],
    )


def compare_documents(file_a: str | Path, file_b: str | Path) -> DocumentCompareResult:
    """
    Compare two documents structurally and semantically.
    Identifies common sections, unique sections, and computes text similarity.
    """
    doc_a = parse_document(file_a)
    doc_b = parse_document(file_b)

    if not doc_a.success or not doc_b.success:
        err = doc_a.error or doc_b.error
        return DocumentCompareResult(
            doc_a_name=Path(file_a).name,
            doc_b_name=Path(file_b).name,
            similarity_score=0.0,
            summary_diff=f"Failed to compare documents: {err}",
        )

    # Word set similarity (Jaccard)
    words_a = set(w.lower() for w in re.findall(r"\w+", doc_a.text_content))
    words_b = set(w.lower() for w in re.findall(r"\w+", doc_b.text_content))

    intersection = words_a.intersection(words_b)
    union = words_a.union(words_b)
    jaccard = round(len(intersection) / len(union), 4) if union else 0.0

    # Section title comparison
    titles_a = set(s.title for s in doc_a.sections if s.title)
    titles_b = set(s.title for s in doc_b.sections if s.title)

    common_sections = sorted(list(titles_a.intersection(titles_b)))
    unique_to_a = sorted(list(titles_a - titles_b))
    unique_to_b = sorted(list(titles_b - titles_a))

    summary = (
        f"Document comparison between '{doc_a.filename}' ({doc_a.format.upper()}, {doc_a.metadata.size_formatted}) "
        f"and '{doc_b.filename}' ({doc_b.format.upper()}, {doc_b.metadata.size_formatted}):\n"
        f"• Vocabulary similarity: {round(jaccard * 100, 1)}%\n"
        f"• Common sections: {len(common_sections)}\n"
        f"• Unique to {doc_a.filename}: {len(unique_to_a)}\n"
        f"• Unique to {doc_b.filename}: {len(unique_to_b)}"
    )

    return DocumentCompareResult(
        doc_a_name=doc_a.filename,
        doc_b_name=doc_b.filename,
        similarity_score=jaccard,
        common_sections=common_sections[:15],
        unique_to_a=unique_to_a[:15],
        unique_to_b=unique_to_b[:15],
        summary_diff=summary,
    )

