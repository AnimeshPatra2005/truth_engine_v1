"""
Pydantic Schemas for the Courtroom Fact-Checking Engine.
All data models used across the pipeline are defined here.
"""
from typing import List, Optional, Literal, TypedDict
from pydantic import BaseModel, Field


# ==============================================================================
# CLAIM DECOMPOSITION SCHEMAS
# ==============================================================================

class ClaimUnit(BaseModel):
    id: int
    claim_text: str
    topic_category: str = Field(description="Topic category for this claim")
    prosecutor_query: str = Field(description="Search query to find evidence DISPROVING this claim with 'supporting documents' phrase")
    defender_query: str = Field(description="Search query to find evidence SUPPORTING this claim with 'supporting documents' phrase")


class DecomposedClaims(BaseModel):
    implication: str = Field(description="The core narrative or hidden conclusion of the text")
    claims: List[ClaimUnit] = Field(description="List of atomic, de-duplicated claims (Max 5)", max_items=5)


# ==============================================================================
# EVIDENCE SCHEMAS
# ==============================================================================

class Evidence(BaseModel):
    """Single piece of evidence extracted from search results"""
    source_url: str
    key_fact: str = Field(description="Specific fact with numbers/dates/names/citations - NO vague statements")
    side: Literal["prosecutor", "defender"] = Field(description="Which side this evidence supports")
    suggested_trusted_domains: List[str] = Field(
        description="3-5 domain-specific trusted sources for verification",
        max_items=5
    )


class ClaimEvidence(BaseModel):
    """Evidence collection for a single claim"""
    claim_id: int
    prosecutor_facts: List[Evidence] = Field(max_items=2, description="Top 2 contradicting facts")
    defender_facts: List[Evidence] = Field(max_items=2, description="Top 2 supporting facts")
    extra_evidence: List[Evidence] = Field(
        default=[],
        max_items=2,
        description="Tangential facts that help verify the overall implication, not this specific claim"
    )


class VerifiedEvidence(BaseModel):
    """Evidence after 3-tier fact-checking"""
    source_url: str
    key_fact: str
    side: Literal["prosecutor", "defender"]
    trust_score: Literal["High", "Medium", "Low"]
    verification_method: str = Field(description="Which tier verified this: Tier1-FactCheck / Tier2-Domain / Tier3-Consensus")
    verification_details: str = Field(description="Details of verification result")
    supporting_urls: List[str] = Field(default=[], description="Consensus URLs that agreed with this fact (for Tier 3 only)")


# ==============================================================================
# ANALYSIS & VERDICT SCHEMAS
# ==============================================================================

class ClaimAnalysis(BaseModel):
    """Analysis for a single claim"""
    claim_id: int
    claim_text: str
    status: Literal["Verified", "Debunked", "Unclear"]
    detailed_paragraph: str = Field(description="Crystal clear explanation (150-250 words) considering both sides")
    prosecutor_evidence: List[VerifiedEvidence] = Field(max_items=2)
    defender_evidence: List[VerifiedEvidence] = Field(max_items=2)


class FinalVerdict(BaseModel):
    overall_verdict: Literal["True", "False", "Partially True", "Unverified"]
    implication_connection: str = Field(description="Long detailed paragraph (200-300 words) connecting implication to claims")
    claim_analyses: List[ClaimAnalysis]


# ==============================================================================
# STATE SCHEMA (for LangGraph)
# ==============================================================================

class CourtroomState(TypedDict):
    transcript: str
    decomposed_data: Optional[DecomposedClaims]
    all_claim_evidence: Optional[List[ClaimEvidence]]
    verified_evidence: Optional[List[dict]]
    final_verdict: Optional[FinalVerdict]
    case_id: Optional[str]  # Vector DB case ID
