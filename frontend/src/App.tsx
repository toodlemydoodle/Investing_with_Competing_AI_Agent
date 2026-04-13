import { useEffect, useState, useTransition } from 'react';

import { type DashboardOverview, getOverview, testBroker, updateMode } from './lib/api';
import { ArenaPage } from './pages/ArenaPage';
import { PortfolioPage } from './pages/PortfolioPage';
import { ResearchPage } from './pages/ResearchPage';
import { TradesPage } from './pages/TradesPage';
import { SystemPage } from './pages/SystemPage';

type Tab = 'arena' | 'portfolio' | 'research' | 'trades' | 'system';

const TABS: { id: Tab; label: string }[] = [
  { id: 'arena', label: 'Arena' },
  { id: 'portfolio', label: 'Portfolio' },
  { id: 'research', label: 'Research' },
  { id: 'trades', label: 'Trades' },
  { id: 'system', label: 'System' },
];

export default function App() {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('arena');
  const [isPending, startTransition] = useTransition();
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const data = await getOverview();
      setOverview(data);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load dashboard.');
    }
  };

  useEffect(() => {
    let isMounted = true;
    const safeLoad = async () => {
      try {
        const data = await getOverview();
        if (isMounted) {
          setOverview(data);
          setLoadError(null);
        }
      } catch (err) {
        if (isMounted) {
          setLoadError(err instanceof Error ? err.message : 'Failed to load dashboard.');
        }
      }
    };
    void safeLoad();
    const timer = window.setInterval(() => void safeLoad(), 15000);
    return () => {
      isMounted = false;
      window.clearInterval(timer);
    };
  }, []);

  const handleChangeMode = (mode: string) => {
    startTransition(() => {
      void (async () => {
        try {
          await updateMode(mode);
          await load();
          setNotice(`Mode changed to ${mode}.`);
          setError(null);
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Mode update failed.');
        }
      })();
    });
  };

  const handleRefreshBroker = () => {
    startTransition(() => {
      void (async () => {
        try {
          const data = await testBroker();
          setOverview(data);
          setNotice('Broker sync completed.');
          setError(null);
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Broker sync failed.');
        }
      })();
    });
  };

  const handleRefreshed = () => {
    void load();
  };

  if (loadError) {
    return (
      <main className="app-shell">
        <p className="banner error">{loadError}</p>
      </main>
    );
  }

  if (!overview) {
    return (
      <main className="app-shell">
        <div className="loading-state">
          <p className="eyebrow">Moomoo Picks Trader</p>
          <p style={{ color: 'var(--muted)' }}>Loading dashboard…</p>
        </div>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="app-wordmark">
          <span className="eyebrow" style={{ margin: 0 }}>Moomoo Picks Trader</span>
        </div>
        <nav className="tab-nav" role="tablist">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={activeTab === tab.id}
              className={`tab-btn${activeTab === tab.id ? ' active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>

      <div className="tab-content">
        {activeTab === 'arena' && (
          <ArenaPage
            overview={overview}
            isPending={isPending}
            onChangeMode={handleChangeMode}
            onRefreshBroker={handleRefreshBroker}
            notice={notice}
            error={error}
          />
        )}
        {activeTab === 'portfolio' && <PortfolioPage overview={overview} />}
        {activeTab === 'research' && <ResearchPage overview={overview} onRefreshed={handleRefreshed} />}
        {activeTab === 'trades' && <TradesPage overview={overview} onOrderPlaced={handleRefreshed} />}
        {activeTab === 'system' && <SystemPage overview={overview} onRefreshed={handleRefreshed} />}
      </div>
    </main>
  );
}
