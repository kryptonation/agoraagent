import { useState, useEffect, useRef } from 'react';
import { 
  Sparkles, 
  Brain, 
  Database, 
  History, 
  Play, 
  Check, 
  AlertCircle, 
  FileText, 
  User, 
  Loader,
  RefreshCw,
  Edit2
} from 'lucide-react';
import './App.css';

interface Message {
  sender: string;
  role: 'buyer' | 'seller' | 'system';
  content: string;
}

interface Checkpoint {
  rounds: number;
  current_price: number | null;
  current_terms: string | null;
  last_proposed_by: string | null;
  status: string;
  agreement_draft: string | null;
}

interface HistoryItem {
  id: number;
  buyer_id: string;
  seller_id: string;
  item_name: string;
  status: string;
  final_price: number;
  rounds: number;
  timestamp: string;
}

interface ProfileItem {
  agent_id: string;
  notes: string;
  last_updated: string;
}

export default function App() {
  // Navigation tabs: 'simulation' | 'history' | 'profiles'
  const [activeTab, setActiveTab] = useState<'simulation' | 'history' | 'profiles'>('simulation');

  // Negotiation configuration
  const [itemName, setItemName] = useState('Custom API Integration');
  const [buyerMax, setBuyerMax] = useState(1500);
  const [buyerTarget, setBuyerTarget] = useState(1100);
  const [sellerMin, setSellerMin] = useState(900);
  const [sellerTarget, setSellerTarget] = useState(1300);

  // Active negotiation state
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [checkpoint, setCheckpoint] = useState<Checkpoint>({
    rounds: 0,
    current_price: null,
    current_terms: null,
    last_proposed_by: null,
    status: 'active',
    agreement_draft: null
  });
  
  // Streaming state
  const [isStreaming, setIsStreaming] = useState(false);
  const [isBreakpoint, setIsBreakpoint] = useState(false);
  const [memoryStatus, setMemoryStatus] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  
  // Human in the loop action choices
  // Choices: 'approve' | 'reject' | 'revision'
  const [buyerChoice, setBuyerChoice] = useState<'approve' | 'reject' | 'revision'>('approve');
  const [buyerRevisionFeedback, setBuyerRevisionFeedback] = useState('');
  
  const [sellerChoice, setSellerChoice] = useState<'approve' | 'reject' | 'revision'>('approve');
  const [sellerRevisionFeedback, setSellerRevisionFeedback] = useState('');

  // Loaded database references
  const [buyerMemoryContext, setBuyerMemoryContext] = useState('Loading relationship notes...');
  const [sellerMemoryContext, setSellerMemoryContext] = useState('Loading relationship notes...');
  const [historyList, setHistoryList] = useState<HistoryItem[]>([]);
  const [profileList, setProfileList] = useState<ProfileItem[]>([]);
  
  // Ref for auto scroll
  const chatBottomRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Load profiles on startup to show current context
  useEffect(() => {
    fetchMemoryContexts();
    fetchHistory();
    fetchProfiles();
  }, []);

  // Auto-scroll chat window
  useEffect(() => {
    if (chatBottomRef.current) {
      chatBottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isStreaming, isBreakpoint]);

  // Clean up EventSource on unmount
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  const fetchMemoryContexts = async () => {
    try {
      const res = await fetch('/api/profiles');
      if (res.ok) {
        const data: ProfileItem[] = await res.json();
        const buyerAgentProfile = data.find(p => p.agent_id === 'BuyerAgent');
        const sellerAgentProfile = data.find(p => p.agent_id === 'SellerAgent');
        
        // BuyerAgent holds memory on SellerAgent
        setBuyerMemoryContext(sellerAgentProfile ? sellerAgentProfile.notes : 'No prior interaction record found for agent SellerAgent. Treat them as a new connection.');
        // SellerAgent holds memory on BuyerAgent
        setSellerMemoryContext(buyerAgentProfile ? buyerAgentProfile.notes : 'No prior interaction record found for agent BuyerAgent. Treat them as a new connection.');
      }
    } catch (e) {
      console.error("Failed to load memories", e);
    }
  };

  const fetchHistory = async () => {
    try {
      const res = await fetch('/api/history');
      if (res.ok) {
        const data = await res.json();
        setHistoryList(data);
      }
    } catch (e) {
      console.error("Failed to load history", e);
    }
  };

  const fetchProfiles = async () => {
    try {
      const res = await fetch('/api/profiles');
      if (res.ok) {
        const data = await res.json();
        setProfileList(data);
      }
    } catch (e) {
      console.error("Failed to load profiles", e);
    }
  };

  const updateProfileInDb = async (agentId: string, notes: string) => {
    try {
      const res = await fetch(`/api/profiles/${agentId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes })
      });
      if (res.ok) {
        fetchProfiles();
        fetchMemoryContexts();
      }
    } catch (e) {
      console.error("Failed to update profile", e);
    }
  };

  const startNegotiation = async () => {
    setErrorMsg(null);
    setIsBreakpoint(false);
    setMemoryStatus(null);
    setMessages([]);
    setCheckpoint({
      rounds: 0,
      current_price: null,
      current_terms: null,
      last_proposed_by: null,
      status: 'active',
      agreement_draft: null
    });

    try {
      // 1. Create a session on the backend
      const res = await fetch('/api/negotiate/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          item_name: itemName,
          buyer_max: buyerMax,
          buyer_target: buyerTarget,
          seller_min: sellerMin,
          seller_target: sellerTarget
        })
      });

      if (!res.ok) {
        throw new Error("Could not initialize negotiation session");
      }

      const data = await res.json();
      setThreadId(data.thread_id);
      
      // 2. Open EventSource to stream
      connectStream(data.thread_id);
    } catch (err: any) {
      setErrorMsg(err.message || "An unexpected error occurred");
    }
  };

  const connectStream = (id: string) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setIsStreaming(true);
    const es = new EventSource(`/api/negotiate/stream/${id}`);
    eventSourceRef.current = es;

    // Handle messages stream
    es.addEventListener('message', (e) => {
      const data = JSON.parse(e.data);
      setMessages(prev => [...prev, data]);
    });

    // Handle state checkpoints
    es.addEventListener('checkpoint', (e) => {
      const data = JSON.parse(e.data);
      setCheckpoint(data);
    });

    // Handle breakpoints
    es.addEventListener('breakpoint', () => {
      setIsBreakpoint(true);
      setIsStreaming(false);
      es.close();
    });

    // Handle final conclusions
    es.addEventListener('concluded', (e) => {
      const data = JSON.parse(e.data);
      setCheckpoint(prev => ({
        ...prev,
        status: data.status,
        agreement_draft: data.agreement_draft,
        current_price: data.final_price,
        rounds: data.rounds
      }));
      setIsStreaming(false);
      es.close();
      
      // Refresh DB summaries
      fetchHistory();
      fetchProfiles();
    });

    // Handle memory updating
    es.addEventListener('memory_updating', (e) => {
      const data = JSON.parse(e.data);
      setMemoryStatus(data.message);
    });

    // Handle memory finished updating
    es.addEventListener('memory_updated', () => {
      setMemoryStatus("Memory summaries compiled successfully and SQLite updated.");
      fetchProfiles();
      fetchMemoryContexts();
    });

    // Handle stream errors
    es.addEventListener('error', () => {
      console.error("SSE stream error");
      setIsStreaming(false);
      es.close();
    });
  };

  const submitHumanActions = async () => {
    if (!threadId) return;

    // Calculate text feedback based on selections
    let buyerFeedback = "APPROVED";
    if (buyerChoice === 'reject') {
      buyerFeedback = "REJECTED";
    } else if (buyerChoice === 'revision') {
      buyerFeedback = buyerRevisionFeedback.trim() || "Please negotiate for a lower price.";
    }

    let sellerFeedback = "APPROVED";
    if (sellerChoice === 'reject') {
      sellerFeedback = "REJECTED";
    } else if (sellerChoice === 'revision') {
      sellerFeedback = sellerRevisionFeedback.trim() || "Please negotiate for a higher price.";
    }

    try {
      setIsBreakpoint(false);
      setIsStreaming(true);

      const res = await fetch(`/api/negotiate/submit-action/${threadId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          buyer_feedback: buyerFeedback,
          seller_feedback: sellerFeedback
        })
      });

      if (!res.ok) {
        throw new Error("Failed to submit actions");
      }

      // Reconnect standard stream to listen for updates
      connectStream(threadId);
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to submit actions");
      setIsStreaming(false);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status.toLowerCase()) {
      case 'active':
        return <span className="badge badge-active">Negotiating</span>;
      case 'agreed':
        return <span className="badge badge-agreed">Awaiting Signatures</span>;
      case 'signed':
        return <span className="badge badge-signed">Contract Signed</span>;
      case 'aborted':
        return <span className="badge badge-aborted">Walked Away</span>;
      default:
        return <span className="badge badge-active">{status}</span>;
    }
  };

  return (
    <div className="app-container">
      {/* Top Header */}
      <header className="header">
        <div className="logo-container">
          <Brain className="logo-icon" size={28} />
          <div className="title-container">
            <h1>AgoraAgent</h1>
            <div className="subtitle">LANGGRAPH NEGOTIATION SIMULATOR v2.0</div>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="tabs">
          <button 
            className={`tab-btn ${activeTab === 'simulation' ? 'active' : ''}`}
            onClick={() => setActiveTab('simulation')}
          >
            <Sparkles size={16} />
            Simulation
          </button>
          <button 
            className={`tab-btn ${activeTab === 'profiles' ? 'active' : ''}`}
            onClick={() => setActiveTab('profiles')}
          >
            <Database size={16} />
            Counterpart Memory
          </button>
          <button 
            className={`tab-btn ${activeTab === 'history' ? 'active' : ''}`}
            onClick={() => setActiveTab('history')}
          >
            <History size={16} />
            Deal Logs
          </button>
        </div>
      </header>

      {/* Main Body Grid */}
      <main className="main-content">
        {activeTab === 'simulation' && (
          <>
            {/* Left Column - Configurations & Live Status */}
            <div className="panel">
              {/* Configuration Card */}
              <div className="card">
                <div className="card-title">
                  <Play size={16} />
                  Parameters Configurator
                </div>
                
                <div className="form-grid">
                  <div className="input-group">
                    <label htmlFor="item-name">Negotiation Item / Service</label>
                    <input 
                      id="item-name"
                      type="text" 
                      value={itemName} 
                      onChange={(e) => setItemName(e.target.value)} 
                      placeholder="e.g. Custom API Integration"
                      disabled={isStreaming || isBreakpoint}
                    />
                  </div>

                  <div className="form-row">
                    <div className="input-group">
                      <label htmlFor="buyer-max">Buyer Max Budget ($)</label>
                      <input 
                        id="buyer-max"
                        type="number" 
                        value={buyerMax} 
                        onChange={(e) => setBuyerMax(Number(e.target.value))}
                        disabled={isStreaming || isBreakpoint}
                      />
                    </div>
                    <div className="input-group">
                      <label htmlFor="buyer-target">Buyer Target ($)</label>
                      <input 
                        id="buyer-target"
                        type="number" 
                        value={buyerTarget} 
                        onChange={(e) => setBuyerTarget(Number(e.target.value))}
                        disabled={isStreaming || isBreakpoint}
                      />
                    </div>
                  </div>

                  <div className="form-row">
                    <div className="input-group">
                      <label htmlFor="seller-min">Seller Min Price ($)</label>
                      <input 
                        id="seller-min"
                        type="number" 
                        value={sellerMin} 
                        onChange={(e) => setSellerMin(Number(e.target.value))}
                        disabled={isStreaming || isBreakpoint}
                      />
                    </div>
                    <div className="input-group">
                      <label htmlFor="seller-target">Seller Target ($)</label>
                      <input 
                        id="seller-target"
                        type="number" 
                        value={sellerTarget} 
                        onChange={(e) => setSellerTarget(Number(e.target.value))}
                        disabled={isStreaming || isBreakpoint}
                      />
                    </div>
                  </div>

                  <button 
                    className="btn btn-primary"
                    onClick={startNegotiation}
                    disabled={isStreaming || isBreakpoint || !itemName}
                  >
                    {isStreaming ? (
                      <>
                        <Loader className="spinner" size={16} />
                        Simulating...
                      </>
                    ) : (
                      <>
                        <Play size={16} />
                        Start Negotiation
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Live Session Status */}
              {threadId && (
                <div className="card">
                  <div className="card-title">
                    <History size={16} />
                    Live Status Hub
                  </div>
                  
                  <div className="status-list">
                    <div className="status-item">
                      <span className="status-label">Session ID</span>
                      <span className="status-value" style={{fontFamily: 'var(--font-mono)'}}>{threadId}</span>
                    </div>
                    <div className="status-item">
                      <span className="status-label">Status</span>
                      {getStatusBadge(checkpoint.status)}
                    </div>
                    <div className="status-item">
                      <span className="status-label">Alternating Round</span>
                      <span className="status-value">{checkpoint.rounds} / 10</span>
                    </div>
                    <div className="status-item">
                      <span className="status-label">Current Offer Price</span>
                      <span className="status-value price-display">
                        {checkpoint.current_price ? `$${checkpoint.current_price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : '—'}
                      </span>
                    </div>
                    {checkpoint.current_terms && (
                      <div className="status-item" style={{flexDirection: 'column', alignItems: 'flex-start', gap: '4px'}}>
                        <span className="status-label">Current Terms Proposal</span>
                        <span className="status-value" style={{fontSize: '12px', fontWeight: 'normal', color: 'var(--text-secondary)'}}>{checkpoint.current_terms}</span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Memory Insights Card */}
              <div className="card">
                <div className="card-title">
                  <Brain size={16} />
                  Cognitive Relationship Memory
                </div>
                
                <div className="form-grid">
                  <div className="input-group">
                    <label>Buyer Agent's Memory on SellerAgent</label>
                    <div className="memory-box">{buyerMemoryContext}</div>
                  </div>
                  
                  <div className="input-group">
                    <label>Seller Agent's Memory on BuyerAgent</label>
                    <div className="memory-box">{sellerMemoryContext}</div>
                  </div>
                </div>
              </div>
            </div>

            {/* Right Column - Conversation Workspace */}
            <div className="panel" style={{flexGrow: 1}}>
              <div className="card chat-card">
                <div className="card-title">
                  <FileText size={16} />
                  Negotiation Log Thread
                </div>

                {/* Messages stream */}
                <div className="chat-messages">
                  {messages.length === 0 && !isStreaming && (
                    <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)'}}>
                      <Brain size={48} style={{opacity: 0.15, marginBottom: '16px'}} />
                      <p>Configure constraints and run a negotiation above.</p>
                      <p style={{fontSize: '12px', marginTop: '4px'}}>Bedrock-backed autonomous agents will negotiate within privacy bounds.</p>
                    </div>
                  )}

                  {messages.map((msg, index) => (
                    <div key={index} className={`message ${msg.role}`}>
                      <div className="msg-header">
                        <User size={12} />
                        {msg.sender === 'BuyerAgent' ? 'Buyer (Agent Delegate)' : msg.sender === 'SellerAgent' ? 'Seller (Agent Delegate)' : msg.sender}
                      </div>
                      <div className="msg-bubble">
                        {msg.content}
                      </div>
                    </div>
                  ))}

                  {isStreaming && (
                    <div className="loading-indicator">
                      <Loader className="spinner" size={14} />
                      <span>Agent is reasoning and formulating counter-proposal...</span>
                    </div>
                  )}
                  
                  <div ref={chatBottomRef} />
                </div>

                {/* Cognitive memory update in progress banner */}
                {memoryStatus && (
                  <div className="memory-update-alert">
                    <Sparkles size={16} className="logo-icon" />
                    <span>{memoryStatus}</span>
                  </div>
                )}

                {/* Error Banner */}
                {errorMsg && (
                  <div className="memory-update-alert" style={{borderColor: 'rgba(239, 68, 68, 0.4)', background: 'var(--color-danger-bg)', color: '#ef4444'}}>
                    <AlertCircle size={16} />
                    <span>{errorMsg}</span>
                  </div>
                )}

                {/* human-in-the-loop signatures block */}
                {isBreakpoint && checkpoint.agreement_draft && (
                  <div className="breakpoint-panel">
                    <div className="breakpoint-header">
                      <AlertCircle size={20} />
                      <span>Human-in-the-Loop Interruption: Signatures Required</span>
                    </div>
                    
                    <div className="contract-preview">
                      {checkpoint.agreement_draft}
                    </div>

                    <div className="signing-section">
                      {/* Buyer Owner Review */}
                      <div className="sign-box">
                        <div className="sign-title buyer">
                          <User size={14} />
                          Buyer Human Owner
                        </div>
                        <div className="choice-buttons">
                          <button 
                            className={`btn-choice ${buyerChoice === 'approve' ? 'selected-approve' : ''}`}
                            onClick={() => setBuyerChoice('approve')}
                          >
                            Sign Contract
                          </button>
                          <button 
                            className={`btn-choice ${buyerChoice === 'reject' ? 'selected-reject' : ''}`}
                            onClick={() => setBuyerChoice('reject')}
                          >
                            Reject
                          </button>
                        </div>
                        <div className="choice-buttons" style={{gridTemplateColumns: '1fr'}}>
                          <button 
                            className={`btn-choice ${buyerChoice === 'revision' ? 'selected-revision' : ''}`}
                            onClick={() => setBuyerChoice('revision')}
                          >
                            Request Revisions
                          </button>
                        </div>
                        
                        {buyerChoice === 'revision' && (
                          <textarea
                            className="revision-input"
                            value={buyerRevisionFeedback}
                            onChange={(e) => setBuyerRevisionFeedback(e.target.value)}
                            placeholder="Instruct your agent delegate on what edits/pricing changes to push for..."
                            rows={2}
                          />
                        )}
                      </div>

                      {/* Seller Owner Review */}
                      <div className="sign-box">
                        <div className="sign-title seller">
                          <User size={14} />
                          Seller Human Owner
                        </div>
                        <div className="choice-buttons">
                          <button 
                            className={`btn-choice ${sellerChoice === 'approve' ? 'selected-approve' : ''}`}
                            onClick={() => setSellerChoice('approve')}
                          >
                            Sign Contract
                          </button>
                          <button 
                            className={`btn-choice ${sellerChoice === 'reject' ? 'selected-reject' : ''}`}
                            onClick={() => setSellerChoice('reject')}
                          >
                            Reject
                          </button>
                        </div>
                        <div className="choice-buttons" style={{gridTemplateColumns: '1fr'}}>
                          <button 
                            className={`btn-choice ${sellerChoice === 'revision' ? 'selected-revision' : ''}`}
                            onClick={() => setSellerChoice('revision')}
                          >
                            Request Revisions
                          </button>
                        </div>
                        
                        {sellerChoice === 'revision' && (
                          <textarea
                            className="revision-input"
                            value={sellerRevisionFeedback}
                            onChange={(e) => setSellerRevisionFeedback(e.target.value)}
                            placeholder="Instruct your agent delegate on what edits/pricing changes to push for..."
                            rows={2}
                          />
                        )}
                      </div>
                    </div>

                    <button 
                      className="btn btn-primary"
                      onClick={submitHumanActions}
                      style={{width: '100%'}}
                    >
                      <Check size={16} />
                      Submit Actions & Resume Negotiation
                    </button>
                  </div>
                )}
              </div>
            </div>
          </>
        )}

        {/* Tab 2: Agent Memory Editing */}
        {activeTab === 'profiles' && (
          <div className="panel" style={{gridColumn: '1 / -1'}}>
            <div className="card">
              <div className="card-title">
                <Brain size={18} />
                Manage SQLite Cognitive Agent Memory Profiles
              </div>
              <p style={{color: 'var(--text-secondary)', fontSize: '13px', marginBottom: '20px'}}>
                These records represent what each agent has learned from previous transactions with the counterpart. They are automatically injected into system instructions for future runs. You can edit them manually below.
              </p>

              <div className="profiles-grid">
                {profileList.map((prof) => (
                  <div key={prof.agent_id} className="card" style={{padding: '16px', background: 'rgba(0,0,0,0.1)'}}>
                    <div className="sign-title" style={{color: 'var(--color-accent)', justifyContent: 'space-between'}}>
                      <span style={{display: 'flex', alignItems: 'center', gap: '8px'}}>
                        <User size={16} />
                        {prof.agent_id} Memory File
                      </span>
                      <span style={{fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)'}}>
                        Last updated: {new Date(prof.last_updated).toLocaleString()}
                      </span>
                    </div>

                    <div className="profile-editor" style={{marginTop: '12px'}}>
                      <textarea
                        className="profile-textarea"
                        value={prof.notes}
                        onChange={(e) => {
                          const val = e.target.value;
                          setProfileList(prev => prev.map(p => p.agent_id === prof.agent_id ? { ...p, notes: val } : p));
                        }}
                      />
                      <button 
                        className="btn btn-secondary"
                        onClick={() => updateProfileInDb(prof.agent_id, prof.notes)}
                        style={{alignSelf: 'flex-end'}}
                      >
                        <Edit2 size={12} />
                        Save Profile Notes
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Tab 3: Historic Database Logs */}
        {activeTab === 'history' && (
          <div className="panel" style={{gridColumn: '1 / -1'}}>
            <div className="card">
              <div className="card-title" style={{justifyContent: 'space-between'}}>
                <span style={{display: 'flex', alignItems: 'center', gap: '8px'}}>
                  <Database size={18} />
                  SQLite Negotiation Transaction History Log
                </span>
                <button 
                  className="btn btn-secondary" 
                  onClick={fetchHistory}
                  style={{padding: '6px 12px', fontSize: '12px'}}
                >
                  <RefreshCw size={12} />
                  Refresh
                </button>
              </div>
              <p style={{color: 'var(--text-secondary)', fontSize: '13px', marginBottom: '20px'}}>
                This is a real-time log of negotiation simulations stored in the sqlite backend database (`memory.db`).
              </p>

              <div className="table-container">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Timestamp</th>
                      <th>Negotiated Item</th>
                      <th>Buyer</th>
                      <th>Seller</th>
                      <th>Deal Price</th>
                      <th>Rounds</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {historyList.length === 0 && (
                      <tr>
                        <td colSpan={8} style={{textAlign: 'center', color: 'var(--text-muted)', padding: '24px'}}>
                          No history logged. Run and execute a simulation first!
                        </td>
                      </tr>
                    )}
                    {historyList.map((item) => (
                      <tr key={item.id}>
                        <td style={{fontFamily: 'var(--font-mono)', fontSize: '12px'}}>{item.id}</td>
                        <td style={{fontSize: '12px', color: 'var(--text-secondary)'}}>{new Date(item.timestamp).toLocaleString()}</td>
                        <td style={{fontWeight: 600}}>{item.item_name}</td>
                        <td style={{color: 'var(--color-buyer)'}}>{item.buyer_id}</td>
                        <td style={{color: 'var(--color-seller)'}}>{item.seller_id}</td>
                        <td style={{fontFamily: 'var(--font-mono)'}}>
                          {item.final_price > 0 ? `$${item.final_price.toLocaleString(undefined, {minimumFractionDigits: 2})}` : '—'}
                        </td>
                        <td>{item.rounds}</td>
                        <td>{getStatusBadge(item.status)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
