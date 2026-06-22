from typing import Annotated, List, Optional
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

# Structured output for agent offers
class NegotiationOffer(BaseModel):
    price: float = Field(description="The proposed price for the item or service.")
    terms: str = Field(description="Any specific conditions, deadlines, or scope boundaries proposed.")
    decision: str = Field(description="One of: 'offer' (suggesting a price), 'accept' (agreeing to the last proposal), or 'abort' (walk away).")
    rationale: str = Field(description="Private thought process leading to this decision (explained to the human, not directly in the chat).")

# The unified state for the negotiation thread
class NegotiationState(TypedDict):
    # Chat transcript (visible to both agents)
    messages: Annotated[List[BaseMessage], add_messages]
    
    # Negotiation Context
    buyer_id: str
    seller_id: str
    item_name: str
    
    # Current proposal on the table
    current_price: Optional[float]
    current_terms: Optional[str]
    last_proposed_by: Optional[str]  # "buyer" or "seller"
    
    # State flags
    rounds: int
    status: str  # "active", "agreed", "aborted", "signed"
    
    # Final agreement document draft
    agreement_draft: Optional[str]
    
    # Human feedbacks
    buyer_feedback: Optional[str]
    seller_feedback: Optional[str]

    # Archetype classification features
    buyer_archetype: Optional[str]
    buyer_strategy: Optional[str]
    seller_archetype: Optional[str]
    seller_strategy: Optional[str]
