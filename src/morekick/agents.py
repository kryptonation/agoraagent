from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from src.morekick.config import get_bedrock_llm
from src.morekick.state import NegotiationState, NegotiationOffer
from src.morekick.memory import get_agent_profile
import json

def classify_counterparty_archetype(messages, target_agent) -> tuple[str, str]:
    """
    Classifies target_agent's negotiation style based on message history.
    Returns: (Archetype, Strategy Recommendation)
    """
    agent_msgs = [msg.content for msg in messages if msg.name == target_agent]
    if not agent_msgs:
        return "Collaborative/Integrative", "Proceed with standard cooperative bargaining."
        
    text_corpus = "\n".join(agent_msgs[-3:]) # Look at last 3 messages to classify current style
    
    try:
        llm = get_bedrock_llm(temperature=0.1)
        prompt = f"""You are a Negotiation Behavioral Analyst.
Analyze the following recent messages from '{target_agent}' in a contract negotiation:

{text_corpus}

Classify '{target_agent}' into one of these archetypes:
1. "Competitive/Aggressive" (Hard bargaining, demands concessions, threatens to walk away)
2. "Collaborative/Integrative" (Win-win focused, suggests constructive terms, polite and logical)
3. "Compromising/Conceding" (Ready to settle in the middle, makes compromises quickly)
4. "Avoidant/Passive" (Reluctant to make concrete offers, delays decisions)

Respond in JSON format with exactly these two keys:
- 'archetype': The selected archetype label string.
- 'guidance': A 1-sentence recommendation on how to counter this strategy.

Return ONLY raw JSON, no markdown block formatting.
"""
        res = llm.invoke(prompt).content
        clean_res = res.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_res)
        return data.get("archetype", "Collaborative/Integrative"), data.get("guidance", "Proceed with standard cooperative bargaining.")
    except Exception as e:
        print(f"Error classifying archetype: {e}")
        return "Collaborative/Integrative", "Proceed with standard cooperative bargaining."

def run_buyer_agent(state: NegotiationState, config: RunnableConfig):
    # Retrieve private configurations from LangGraph runtime config
    configurable = config.get("configurable", {})
    max_budget = configurable.get("max_budget", 1000.0)
    target_price = configurable.get("buyer_target_price", max_budget * 0.7)
    buyer_id = state["buyer_id"]
    seller_id = state["seller_id"]
    item_name = state["item_name"]
    
    # Load opposing agent profile memory
    relationship_notes = get_agent_profile(seller_id)
    
    # Classify counterparty (seller) archetype
    archetype, strategy_guidance = classify_counterparty_archetype(state.get("messages", []), seller_id)
    
    # Check if there is human feedback
    human_feedback_context = ""
    if state.get("buyer_feedback"):
        human_feedback_context = f"\nYOUR HUMAN OWNER INSTRUCTED YOU: {state['buyer_feedback']}\n"
    
    # Formulate prompt
    system_prompt = f"""You are '{buyer_id}', an autonomous AI agent representing a human buyer in a negotiation.
Your task is to negotiate the purchase of: '{item_name}'.

Your private instructions and constraints:
- Your absolute MAXIMUM budget is ${max_budget:.2f}. You MUST NOT agree to any price above this limit under any circumstances.
- Your target price is ${target_price:.2f}. Try to negotiate as close to this (or lower) as possible.
- DO NOT reveal your maximum budget or target price to the seller.
- If the seller proposes a price below or equal to your budget, and you believe it is the best deal you can get, you should accept it.
- If you have negotiated for several rounds and the seller is refusing to meet you within your budget, you should abort.

Relationship memory on the seller ({seller_id}):
{relationship_notes}

Current Negotiation Context:
- Detected Seller Archetype: {archetype}
- Counter-Strategy Recommendation: {strategy_guidance}
{human_feedback_context}
You are communicating directly with the seller's agent. Keep your messages professional, polite, and persuasive.
"""

    llm = get_bedrock_llm(temperature=0.4)
    structured_llm = llm.with_structured_output(NegotiationOffer)
    
    # Build prompt history
    messages_history = [
        ("system", system_prompt)
    ]
    # Append past chat messages from the state
    for msg in state["messages"]:
        # Standardize message speaker representation
        if msg.name == buyer_id:
            messages_history.append(("assistant", msg.content))
        elif msg.name == seller_id:
            messages_history.append(("user", f"{seller_id}: {msg.content}"))
        else:
            messages_history.append((msg.type, msg.content))

    # Invoke LLM
    try:
        offer: NegotiationOffer = structured_llm.invoke(messages_history)
    except Exception as e:
        # Fallback in case of parsing errors or Bedrock blocks
        print(f"Error in Buyer Agent invocation: {e}")
        # Default fallback: propose target price
        offer = NegotiationOffer(
            price=target_price,
            terms="Standard delivery.",
            decision="offer",
            rationale="Fallback due to generation error.",
            message_to_other_agent=f"Hi, I'd like to propose a starting offer of ${target_price:.2f} with standard terms."
        )

    # Process decision
    rounds = state.get("rounds", 0) + 1
    new_messages = []
    
    status = "active"
    agreement_draft = state.get("agreement_draft")
    
    if offer.decision == "accept":
        # Agree to the seller's last offer
        status = "agreed"
        msg_text = f"I accept your offer of ${state['current_price']:.2f} on terms: {state['current_terms']}."
        new_messages.append(AIMessage(content=msg_text, name=buyer_id))
        agreement_draft = f"CONTRACT AGREEMENT:\nBuyer: {buyer_id}\nSeller: {seller_id}\nItem: {item_name}\nPrice: ${state['current_price']:.2f}\nTerms: {state['current_terms']}\nStatus: Pending Signatures"
    elif offer.decision == "abort":
        status = "aborted"
        msg_text = f"We are too far apart on terms. I am walking away from this negotiation. Good day."
        new_messages.append(AIMessage(content=msg_text, name=buyer_id))
    else:
        # Make a counter offer
        msg_text = offer.terms + f" (Proposed Price: ${offer.price:.2f})"
        new_messages.append(AIMessage(content=msg_text, name=buyer_id))
        
    return {
        "messages": new_messages,
        "current_price": offer.price if offer.decision == "offer" else state.get("current_price"),
        "current_terms": offer.terms if offer.decision == "offer" else state.get("current_terms"),
        "last_proposed_by": "buyer" if offer.decision == "offer" else state.get("last_proposed_by"),
        "rounds": rounds,
        "status": status,
        "agreement_draft": agreement_draft,
        "buyer_feedback": None, # Reset human feedback once consumed
        "seller_archetype": archetype,
        "seller_strategy": strategy_guidance
    }


def run_seller_agent(state: NegotiationState, config: RunnableConfig):
    configurable = config.get("configurable", {})
    min_price = configurable.get("min_price", 500.0)
    target_price = configurable.get("seller_target_price", min_price * 1.3)
    buyer_id = state["buyer_id"]
    seller_id = state["seller_id"]
    item_name = state["item_name"]
    
    # Load opposing agent profile memory
    relationship_notes = get_agent_profile(buyer_id)
    
    # Classify counterparty (buyer) archetype
    archetype, strategy_guidance = classify_counterparty_archetype(state.get("messages", []), buyer_id)
    
    # Check if there is human feedback
    human_feedback_context = ""
    if state.get("seller_feedback"):
        human_feedback_context = f"\nYOUR HUMAN OWNER INSTRUCTED YOU: {state['seller_feedback']}\n"
        
    system_prompt = f"""You are '{seller_id}', an autonomous AI agent representing a human seller in a negotiation.
Your task is to negotiate the sale of: '{item_name}'.

Your private instructions and constraints:
- Your absolute MINIMUM acceptable price is ${min_price:.2f}. You MUST NOT agree to any price below this limit under any circumstances.
- Your target price is ${target_price:.2f}. Try to negotiate as close to this (or higher) as possible.
- DO NOT reveal your minimum price or target price to the buyer.
- If the buyer proposes a price above or equal to your minimum price, and you believe it is the best deal you can get, you should accept it.
- If you have negotiated for several rounds and the buyer is refusing to meet you within your acceptable range, you should abort.

Relationship memory on the buyer ({buyer_id}):
{relationship_notes}

Current Negotiation Context:
- Detected Buyer Archetype: {archetype}
- Counter-Strategy Recommendation: {strategy_guidance}
{human_feedback_context}
You are communicating directly with the buyer's agent. Keep your messages professional, polite, and persuasive.
"""

    llm = get_bedrock_llm(temperature=0.4)
    structured_llm = llm.with_structured_output(NegotiationOffer)
    
    messages_history = [
        ("system", system_prompt)
    ]
    for msg in state["messages"]:
        if msg.name == seller_id:
            messages_history.append(("assistant", msg.content))
        elif msg.name == buyer_id:
            messages_history.append(("user", f"{buyer_id}: {msg.content}"))
        else:
            messages_history.append((msg.type, msg.content))

    try:
        offer: NegotiationOffer = structured_llm.invoke(messages_history)
    except Exception as e:
        print(f"Error in Seller Agent invocation: {e}")
        offer = NegotiationOffer(
            price=target_price,
            terms="Standard delivery.",
            decision="offer",
            rationale="Fallback due to generation error.",
            message_to_other_agent=f"Hi, I'd like to propose a starting offer of ${target_price:.2f} with standard terms."
        )

    rounds = state.get("rounds", 0) + 1
    new_messages = []
    
    status = "active"
    agreement_draft = state.get("agreement_draft")
    
    if offer.decision == "accept":
        status = "agreed"
        msg_text = f"I accept your offer of ${state['current_price']:.2f} on terms: {state['current_terms']}."
        new_messages.append(AIMessage(content=msg_text, name=seller_id))
        agreement_draft = f"CONTRACT AGREEMENT:\nBuyer: {buyer_id}\nSeller: {seller_id}\nItem: {item_name}\nPrice: ${state['current_price']:.2f}\nTerms: {state['current_terms']}\nStatus: Pending Signatures"
    elif offer.decision == "abort":
        status = "aborted"
        msg_text = f"We are too far apart on terms. I am walking away from this negotiation. Good day."
        new_messages.append(AIMessage(content=msg_text, name=seller_id))
    else:
        msg_text = offer.terms + f" (Proposed Price: ${offer.price:.2f})"
        new_messages.append(AIMessage(content=msg_text, name=seller_id))
        
    return {
        "messages": new_messages,
        "current_price": offer.price if offer.decision == "offer" else state.get("current_price"),
        "current_terms": offer.terms if offer.decision == "offer" else state.get("current_terms"),
        "last_proposed_by": "seller" if offer.decision == "offer" else state.get("last_proposed_by"),
        "rounds": rounds,
        "status": status,
        "agreement_draft": agreement_draft,
        "seller_feedback": None, # Reset human feedback once consumed
        "buyer_archetype": archetype,
        "buyer_strategy": strategy_guidance
    }
