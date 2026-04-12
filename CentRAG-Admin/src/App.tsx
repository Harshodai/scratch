
import React, { useState, useEffect } from 'react';
import { 
  BarChart3, 
  FileText, 
  Hexagon, 
  LayoutDashboard, 
  MessageSquare, 
  Search, 
  Settings, 
  UploadCloud, 
  Activity,
  Layers,
  Database,
  Key,
  ChevronRight,
  Terminal,
  ShieldCheck,
  Zap
} from 'lucide-react';

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";

// --- Mock Data & Constants ---
const API_URL = "http://localhost:8000";
const TEAM_ID = "demo-team-123";
const API_KEY = "centrag_dev_token_12345";

export default function CentRAGDashboard() {
  const [activeTab, setActiveTab] = useState("overview");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<any[]>([]);
  const [status, setStatus] = useState({ backend: 'checking', storage: 'checking' });
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  const checkHealth = async () => {
    try {
      const resp = await fetch(`${API_URL}/health`);
      if (resp.ok) {
        setStatus({ backend: 'online', storage: 'online' });
      } else {
        setStatus({ backend: 'degraded', storage: 'offline' });
      }
    } catch (e) {
      setStatus({ backend: 'offline', storage: 'offline' });
    }
  };

  const handleSearch = async () => {
    if (!query) return;
    try {
      const resp = await fetch(`${API_URL}/v1/retrieve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Team-ID': TEAM_ID,
          'X-API-Key': API_KEY
        },
        body: JSON.stringify({
          queries: [query],
          limit: 5
        })
      });
      const data = await resp.json();
      setResults(data.results || []);
    } catch (e) {
      console.error("Search error", e);
    }
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    setUploadStatus("Uploading...");

    const formData = new FormData();
    formData.append('file', file);

    try {
      const resp = await fetch(`${API_URL}/v1/documents`, {
        method: 'POST',
        headers: {
          'X-Team-ID': TEAM_ID,
          'X-API-Key': API_KEY
        },
        body: formData
      });
      
      if (resp.ok) {
          setUploadStatus("✅ Document ingested successfully.");
      } else {
          setUploadStatus("❌ Ingestion failed.");
      }
    } catch (e) {
      setUploadStatus("⚠️ Error connecting to backend.");
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="flex h-screen bg-[#F8FAFC] text-slate-900 font-sans">
      {/* Sidebar */}
      <aside className="w-64 bg-white border-r border-slate-200 flex flex-col shadow-sm">
        <div className="p-6 flex items-center gap-3">
          <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center text-white font-bold shadow-lg shadow-indigo-200">
            C
          </div>
          <span className="font-bold text-xl tracking-tight text-slate-800">CentRAG</span>
        </div>
        
        <nav className="flex-1 px-4 py-4 space-y-1">
          <SidebarItem 
            icon={<LayoutDashboard size={20} />} 
            label="Dashboard" 
            active={activeTab === "overview"} 
            onClick={() => setActiveTab("overview")} 
          />
          <SidebarItem 
            icon={<FileText size={20} />} 
            label="Knowledge Base" 
            active={activeTab === "documents"} 
            onClick={() => setActiveTab("documents")} 
          />
          <SidebarItem 
            icon={<MessageSquare size={20} />} 
            label="Retrieval Lab" 
            active={activeTab === "lab"} 
            onClick={() => setActiveTab("lab")} 
          />
          <Separator className="my-4 opacity-50" />
          <SidebarItem icon={<ShieldCheck size={20} />} label="Guardrails" />
          <SidebarItem icon={<Settings size={20} />} label="Settings" />
        </nav>

        <div className="p-4 mt-auto">
          <div className="bg-slate-50 rounded-xl p-4 border border-slate-100 mb-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Status</span>
              <div className={`w-2 h-2 rounded-full ${status.backend === 'online' ? 'bg-emerald-500 animate-pulse' : 'bg-red-400'}`} />
            </div>
            <p className="text-sm font-medium text-slate-700">Cluster {status.backend}</p>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-8 shadow-sm z-10">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="bg-indigo-50 text-indigo-700 border-indigo-100 font-semibold px-3 py-1">
              TEAM: {TEAM_ID}
            </Badge>
          </div>
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="icon" className="text-slate-500">
              <Activity size={20} />
            </Button>
            <div className="h-8 w-8 bg-slate-200 rounded-full border border-white shadow-sm" />
          </div>
        </header>

        {/* Content Area */}
        <ScrollArea className="flex-1 p-8">
          <div className="max-w-6xl mx-auto space-y-8">
            
            {activeTab === "overview" && (
              <>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                  <StatCard icon={<Layers className="text-indigo-600" />} title="Collections" value="12" sub="active" />
                  <StatCard icon={<Database className="text-emerald-600" />} title="Vectors" value="4.2k" sub="+12 today" />
                  <StatCard icon={<Zap className="text-amber-500" />} title="Latency" value="124ms" sub="avg p95" />
                  <StatCard icon={<ShieldCheck className="text-rose-500" />} title="Blocked" value="0" sub="last 24h" />
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  <Card className="lg:col-span-2 border-slate-200 shadow-sm">
                    <CardHeader>
                      <CardTitle className="text-lg">Recent Documents</CardTitle>
                      <CardDescription>Latest files ingested into the platform.</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-4">
                        {[1, 2, 3].map(i => (
                          <div key={i} className="flex items-center justify-between p-3 rounded-lg hover:bg-slate-50 transition-colors border border-transparent hover:border-slate-100">
                            <div className="flex items-center gap-3">
                              <div className="w-10 h-10 bg-indigo-50 rounded flex items-center justify-center text-indigo-600">
                                <FileText size={20} />
                              </div>
                              <div>
                                <p className="font-medium text-slate-800">system_documentation_v{i}.pdf</p>
                                <p className="text-xs text-slate-500">2.4 MB • 4 mins ago</p>
                              </div>
                            </div>
                            <Button variant="ghost" size="sm">View</Button>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="border-slate-200 shadow-sm">
                    <CardHeader>
                      <CardTitle className="text-lg">Quick Actions</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <Button className="w-full justify-start gap-2 bg-indigo-600 hover:bg-indigo-700" onClick={() => setActiveTab("documents")}>
                        <UploadCloud size={18} />
                        Ingest New File
                      </Button>
                      <Button variant="outline" className="w-full justify-start gap-2 text-slate-700" onClick={() => setActiveTab("lab")}>
                        <Search size={18} />
                        Run Evaluation
                      </Button>
                    </CardContent>
                  </Card>
                </div>
              </>
            )}

            {activeTab === "documents" && (
              <Card className="border-slate-200 shadow-sm">
                 <CardHeader>
                  <CardTitle>Ingestion Portal</CardTitle>
                  <CardDescription>Upload files to process through the extraction pipeline.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="border-2 border-dashed border-slate-200 rounded-2xl p-12 flex flex-col items-center justify-center bg-slate-50 hover:bg-slate-100 transition-colors cursor-pointer group">
                    <div className="w-16 h-16 bg-white rounded-2xl shadow-sm border border-slate-100 flex items-center justify-center text-slate-400 group-hover:text-indigo-600 mb-6 transition-colors">
                      <UploadCloud size={32} />
                    </div>
                    <label className="cursor-pointer">
                      <span className="font-bold text-slate-800 text-lg">Click to upload</span>
                      <input type="file" className="hidden" onChange={handleFileUpload} />
                    </label>
                    <p className="text-slate-500 mt-2">or drag and drop your PDFs here</p>
                    <p className="text-xs text-slate-400 mt-4 italic">Supported: PDF, DOCX, TXT (Max 50MB)</p>
                  </div>

                  {uploadStatus && (
                    <Alert className={uploadStatus.includes("✅") ? "bg-emerald-50 border-emerald-100" : "bg-rose-50 border-rose-100"}>
                      <Terminal className="h-4 w-4" />
                      <AlertTitle>System Response</AlertTitle>
                      <AlertDescription>
                        {uploadStatus}
                      </AlertDescription>
                    </Alert>
                  )}
                </CardContent>
              </Card>
            )}

            {activeTab === "lab" && (
              <div className="space-y-6">
                <Card className="border-slate-200 shadow-sm overflow-hidden">
                  <div className="bg-slate-900 p-4 flex items-center gap-3">
                    <Search className="text-slate-400" size={20} />
                    <input 
                      className="bg-transparent border-none outline-none text-white w-full placeholder:text-slate-500" 
                      placeholder="Enter query to test retrieval..."
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                    />
                    <Button size="sm" className="bg-indigo-500 hover:bg-indigo-600" onClick={handleSearch}>Run</Button>
                  </div>
                  <CardContent className="p-6 bg-white min-h-[400px]">
                    {results.length > 0 ? (
                      <div className="space-y-8">
                        {results.map((r, idx) => (
                           <div key={idx} className="space-y-6">
                              <h3 className="font-bold text-slate-500 text-xs uppercase tracking-widest border-b pb-2 flex items-center gap-2">
                                <Search size={14} /> Query Results
                              </h3>
                              {r.matches.map((m: any, mIdx: number) => (
                                <div key={mIdx} className="bg-slate-50 p-4 rounded-xl border border-slate-100 space-y-3 relative overflow-hidden group">
                                  <div className="absolute top-0 right-0 p-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                    <Badge variant="secondary" className="bg-white">{Math.round(m.score * 100)}% Match</Badge>
                                  </div>
                                  <div className="flex items-center gap-2 text-xs font-bold text-indigo-600">
                                    <Hexagon size={12} /> CHUNK_{mIdx}
                                  </div>
                                  <p className="text-slate-700 leading-relaxed italic border-l-4 border-indigo-200 pl-4">
                                    "{m.content}"
                                  </p>
                                  <div className="flex items-center gap-4 text-[10px] text-slate-400 font-mono uppercase">
                                    <span className="flex items-center gap-1"><FileText size={10} /> {m.metadata.filename || 'unknown'}</span>
                                    <span>Team: {TEAM_ID}</span>
                                  </div>
                                </div>
                              ))}
                           </div>
                        ))}
                      </div>
                    ) : (
                      <div className="flex flex-col items-center justify-center pt-20 text-slate-300">
                        <MessageSquare size={48} className="mb-4 opacity-20" />
                        <p className="font-medium">Run a query to see retrieval context here.</p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            )}

          </div>
        </ScrollArea>
      </main>
    </div>
  );
}

function SidebarItem({ icon, label, active = false, onClick }: { icon: React.ReactNode, label: string, active?: boolean, onClick?: () => void }) {
  return (
    <button 
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-all group ${
        active 
          ? 'bg-indigo-50 text-indigo-700 shadow-sm border border-indigo-100/50' 
          : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'
      }`}
    >
      <span className={`${active ? 'text-indigo-600' : 'text-slate-400 group-hover:text-slate-900'}`}>{icon}</span>
      {label}
      {active && <ChevronRight size={14} className="ml-auto opacity-50" />}
    </button>
  );
}

function StatCard({ icon, title, value, sub }: { icon: React.ReactNode, title: string, value: string, subText?: string }) {
  return (
    <Card className="border-slate-200 shadow-sm hover:shadow-md transition-shadow">
      <CardContent className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="w-10 h-10 bg-slate-50 rounded-lg flex items-center justify-center border border-slate-100">
            {icon}
          </div>
          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">{sub}</span>
        </div>
        <div>
          <h2 className="text-2xl font-bold text-slate-800 tracking-tight">{value}</h2>
          <p className="text-sm font-medium text-slate-500">{title}</p>
        </div>
      </CardContent>
    </Card>
  );
}
