from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import AIMessage

from src.morekick.state import NegotiationState
from src.morekick.agents import run_buyer_agent, run_seller_agent

def generate_agreement_node(state: NegotiationState):
    # This node compiles the final draft of the agreement
    price = state["current_price"]
    terms = state["current_terms"]
    buyer = state["buyer_id"]
    seller = state["seller_id"]
    item = state["item_name"]
    
    draft = f"""========================================
             CONTRACT AGREEMENT
========================================
Item/Service: {item}
Buyer Agent:  {buyer}
Seller Agent: {seller}

Agreed Price: ${price:.2f}
Agreed Terms: {terms}

This agreement is pending official signature approvals
from the respective human owners of both agents.
========================================"""
    
    return {
        "agreement_draft": draft,
        "status": "agreed"
    }

def await_signatures_node(state: NegotiationState):
    # This is a pass-through node that acts as a breakpoint trigger.
    # The graph stops *before* executing this node to await user input.
    return {}

def process_signatures_node(state: NegotiationState):
    buyer_fb = state.get("buyer_feedback")
    seller_fb = state.get("seller_feedback")
    
    # Check if both owners signed
    if buyer_fb == "APPROVED" and seller_fb == "APPROVED":
        final_draft = state["agreement_draft"] + "\n\nSTATUS: SIGNED & EXECUTED BY BOTH PARTIES."
        return {
            "status": "signed",
            "agreement_draft": final_draft
        }
    elif buyer_fb == "REJECTED" or seller_fb == "REJECTED":
        return {
            "status": "aborted"
        }
    else:
        # Re-activate negotiation if feedback is provided instead of signing
        return {
            "status": "active"
        }

# Routing logic after agent execution
def route_after_agent(state: NegotiationState):
    status = state.get("status")
    rounds = state.get("rounds", 0)
    
    if status == "agreed":
        return "generate_agreement"
    elif status == "aborted":
        return END
        
    if rounds >= 10:
        # If rounds exceed cap, force termination
        return END
        
    # Alternate turns
    last_actor = state.get("last_proposed_by")
    if last_actor == "buyer":
        return "seller"
    else:
        return "buyer"

# Routing logic after processing signatures
def route_after_signatures(state: NegotiationState):
    status = state.get("status")
    if status == "signed" or status == "aborted":
        return END
        
    # If status went back to active, route to whoever gave feedback
    if state.get("buyer_feedback"):
        return "buyer"
    else:
        return "seller"

# Compile and build the LangGraph workflow
def build_negotiation_graph():
    workflow = StateGraph(NegotiationState)
    
    # Add Nodes
    workflow.add_node("buyer", run_buyer_agent)
    workflow.add_node("seller", run_seller_agent)
    workflow.add_node("generate_agreement", generate_agreement_node)
    workflow.add_node("await_signatures", await_signatures_node)
    workflow.add_node("process_signatures", process_signatures_node)
    
    # Configure Edges and Routing
    workflow.add_edge(START, "buyer")
    
    workflow.add_conditional_edges(
        "buyer",
        route_after_agent,
        {
            "seller": "seller",
            "generate_agreement": "generate_agreement",
            "__end__": END
        }
    )
    
    workflow.add_conditional_edges(
        "seller",
        route_after_agent,
        {
            "buyer": "buyer",
            "generate_agreement": "generate_agreement",
            "__end__": END
        }
    )
    
    workflow.add_edge("generate_agreement", "await_signatures")
    workflow.add_edge("await_signatures", "process_signatures")
    
    workflow.add_conditional_edges(
        "process_signatures",
        route_after_signatures,
        {
            "buyer": "buyer",
            "seller": "seller",
            "__end__": END
        }
    )
    
    # Compile with memory persistence and breakpoint interrupt before signing
    memory = MemorySaver()
    compiled_graph = workflow.compile(
        checkpointer=memory,
        interrupt_before=["await_signatures"]
    )
    
    return compiled_graph
