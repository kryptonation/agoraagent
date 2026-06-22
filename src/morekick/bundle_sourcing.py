import os
import sys
import uuid
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, AsyncGenerator

from src.morekick.graph import build_negotiation_graph
from src.morekick.memory import get_agent_profile, update_agent_profile, log_negotiation
from src.morekick.config import get_bedrock_llm

logger = logging.getLogger("bundle_sourcing")

# Re-use compiled graph
compiled_graph = build_negotiation_graph()

async def run_bundle_sourcing_session(total_budget: float) -> AsyncGenerator[str, None]:
    bundle_id = f"bundle_{uuid.uuid4().hex[:8]}"
    
    # 1. Define vendor allocations
    # UI/UX Design (30%), Backend Dev (50%), Database (20%)
    vendors = {
        "design": {
            "name": "DesignerAgent",
            "item": "UI/UX Design UI Kit",
            "max_budget": total_budget * 0.3,
            "target_price": total_budget * 0.3 * 0.7,
            "seller_min": total_budget * 0.3 * 0.5,
            "seller_target": total_budget * 0.3 * 0.8,
            "final_price": 0.0,
            "status": "active",
            "rounds": 0
        },
        "development": {
            "name": "DeveloperAgent",
            "item": "Backend API Integration",
            "max_budget": total_budget * 0.5,
            "target_price": total_budget * 0.5 * 0.8,
            "seller_min": total_budget * 0.5 * 0.6,
            "seller_target": total_budget * 0.5 * 0.9,
            "final_price": 0.0,
            "status": "active",
            "rounds": 0
        },
        "database": {
            "name": "DBAdminAgent",
            "item": "Database Optimization Schema",
            "max_budget": total_budget * 0.2,
            "target_price": total_budget * 0.2 * 0.7,
            "seller_min": total_budget * 0.2 * 0.5,
            "seller_target": total_budget * 0.2 * 0.8,
            "final_price": 0.0,
            "status": "active",
            "rounds": 0
        }
    }
    
    logger.info(f"Starting Bundle Sourcing {bundle_id} with budget ${total_budget}")
    
    # Yield initial setup
    yield f"event: bundle_start\ndata: {json.dumps({'bundle_id': bundle_id, 'total_budget': total_budget, 'vendors': vendors})}\n\n"
    await asyncio.sleep(0.5)

    order = ["design", "development", "database"]
    total_spent = 0.0
    
    for v_key in order:
        vendor = vendors[v_key]
        vendor_name = vendor["name"]
        item_name = vendor["item"]
        
        # Log transition system message
        yield f"event: bundle_message\ndata: {json.dumps({'vendor': v_key, 'sender': 'System', 'role': 'system', 'content': f'Starting negotiation for {item_name} with {vendor_name}. Allocated Max Budget: ${vendor[\"max_budget\"]:.2f}'})}\n\n"
        await asyncio.sleep(0.5)
        
        # Yield status checkpoint
        yield f"event: bundle_checkpoint\ndata: {json.dumps({'vendors': vendors, 'total_spent': total_spent})}\n\n"
        
        # Configure thread for this vendor
        thread_id = f"{bundle_id}_{v_key}"
        config = {
            "configurable": {
                "thread_id": thread_id,
                "max_budget": vendor["max_budget"],
                "buyer_target_price": vendor["target_price"],
                "min_price": vendor["seller_min"],
                "seller_target_price": vendor["seller_target"]
            }
        }
        
        state_input = {
            "messages": [],
            "buyer_id": "BuyerAgent",
            "seller_id": vendor_name,
            "item_name": item_name,
            "current_price": None,
            "current_terms": None,
            "last_proposed_by": None,
            "rounds": 0,
            "status": "active",
            "agreement_draft": None,
            "buyer_feedback": None,
            "seller_feedback": None
        }
        
        current_msg_count = 0
        final_state = None
        
        try:
            # Execute LangGraph simulation for this vendor
            async for event in compiled_graph.astream(state_input, config=config, stream_mode="values"):
                final_state = event
                messages = final_state.get("messages", [])
                
                # Stream new messages
                if len(messages) > current_msg_count:
                    for msg in messages[current_msg_count:]:
                        role = "buyer" if msg.name == "BuyerAgent" else "seller" if msg.name == vendor_name else "system"
                        yield f"event: bundle_message\ndata: {json.dumps({'vendor': v_key, 'sender': msg.name, 'role': role, 'content': msg.content})}\n\n"
                    current_msg_count = len(messages)
                
                # Update local rounds
                vendor["rounds"] = final_state.get("rounds", 0)
                vendor["current_price"] = final_state.get("current_price")
                yield f"event: bundle_checkpoint\ndata: {json.dumps({'vendors': vendors, 'total_spent': total_spent})}\n\n"
                await asyncio.sleep(0.2)

            # Check if paused at signature breakpoint
            state_info = compiled_graph.get_state(config)
            if "await_signatures" in state_info.next:
                # Automate human signature approvals for shadow bundle run
                yield f"event: bundle_message\ndata: {json.dumps({'vendor': v_key, 'sender': 'System', 'role': 'system', 'content': 'Draft agreement negotiated. Human signatures auto-approved in bundle simulator.'})}\n\n"
                await asyncio.sleep(0.5)
                
                compiled_graph.update_state(
                    config,
                    {
                        "buyer_feedback": "APPROVED",
                        "seller_feedback": "APPROVED"
                    },
                    as_node="await_signatures"
                )
                
                # Resume execution
                async for event in compiled_graph.astream(None, config=config, stream_mode="values"):
                    final_state = event
                    messages = final_state.get("messages", [])
                    if len(messages) > current_msg_count:
                        for msg in messages[current_msg_count:]:
                            role = "buyer" if msg.name == "BuyerAgent" else "seller" if msg.name == vendor_name else "system"
                            yield f"event: bundle_message\ndata: {json.dumps({'vendor': v_key, 'sender': msg.name, 'role': role, 'content': msg.content})}\n\n"
                        current_msg_count = len(messages)
                    
                    vendor["rounds"] = final_state.get("rounds", 0)
                    vendor["current_price"] = final_state.get("current_price")
                    yield f"event: bundle_checkpoint\ndata: {json.dumps({'vendors': vendors, 'total_spent': total_spent})}\n\n"
                    await asyncio.sleep(0.2)
            
            # Post-negotiation analysis for this vendor
            state_info = compiled_graph.get_state(config)
            final_values = state_info.values
            status = final_values.get("status", "aborted")
            final_price = final_values.get("current_price", 0.0)
            
            vendor["status"] = status
            vendor["final_price"] = final_price if status == "signed" else 0.0
            
            if status == "signed":
                total_spent += final_price
                surplus = vendor["max_budget"] - final_price
                
                yield f"event: bundle_message\ndata: {json.dumps({'vendor': v_key, 'sender': 'System', 'role': 'system', 'content': f'SUCCESS: Contract signed for {item_name} at ${final_price:.2f}.'})}\n\n"
                
                if surplus > 0:
                    # Reallocate surplus to remaining active vendors
                    remaining_keys = [k for k in order if k != v_key and vendors[k]["status"] == "active"]
                    if remaining_keys:
                        split_surplus = surplus / len(remaining_keys)
                        for rk in remaining_keys:
                            vendors[rk]["max_budget"] += split_surplus
                            vendors[rk]["target_price"] += split_surplus * 0.8
                            
                        realloc_msg = f"System: Savings of ${surplus:.2f} reallocated to remaining vendors. Added ${split_surplus:.2f} to max budget of: {', '.join(remaining_keys)}."
                        yield f"event: bundle_message\ndata: {json.dumps({'vendor': v_key, 'sender': 'System', 'role': 'system', 'content': realloc_msg})}\n\n"
                
                # Log outcome to main DB
                log_negotiation("BuyerAgent", vendor_name, item_name, "signed", final_price, vendor["rounds"])
            else:
                yield f"event: bundle_message\ndata: {json.dumps({'vendor': v_key, 'sender': 'System', 'role': 'system', 'content': f'FAILED: Negotiation aborted or failed for {item_name}.'})}\n\n"
                log_negotiation("BuyerAgent", vendor_name, item_name, "aborted", 0.0, vendor["rounds"])
                
            yield f"event: bundle_checkpoint\ndata: {json.dumps({'vendors': vendors, 'total_spent': total_spent})}\n\n"
            await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"Error negotiating bundle vendor {v_key}: {e}")
            vendor["status"] = "failed"
            yield f"event: bundle_message\ndata: {json.dumps({'vendor': v_key, 'sender': 'System', 'role': 'system', 'content': f'ERROR: {str(e)}'})}\n\n"
            yield f"event: bundle_checkpoint\ndata: {json.dumps({'vendors': vendors, 'total_spent': total_spent})}\n\n"

    # 3. Final Conclusion
    savings = total_budget - total_spent
    signed_count = sum(1 for v in vendors.values() if v["status"] == "signed")
    conclusion_status = "success" if signed_count == 3 else "partial" if signed_count > 0 else "failed"
    
    conclusion_data = {
        "status": conclusion_status,
        "total_budget": total_budget,
        "total_spent": total_spent,
        "savings": savings,
        "signed_count": signed_count
    }
    
    yield f"event: bundle_concluded\ndata: {json.dumps(conclusion_data)}\n\n"
    logger.info(f"Bundle sourcing session {bundle_id} finished with status: {conclusion_status}")
