import React, { useState, useEffect } from 'react';
import { SAMPLE_ACTIVITY, SAMPLE_READING, STORAGE_KEYS, DEFAULT_BACKEND_URL } from './constants';
import { getComfortBand } from './utils';
import { RoomView, ActivityView, SettingsView, ControlsView } from './components';

type Tab = "Room" | "Controls" | "Activity" | "Settings";

const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<Tab>("Room");
  const [backendUrl, setBackendUrl] = useState<string>("");
  const [saveStatus, setSaveStatus] = useState<boolean>(false);
  const [reading, setReading] = useState(SAMPLE_READING);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEYS.BACKEND_URL);
    setBackendUrl(stored || DEFAULT_BACKEND_URL);
  }, []);

  const handleSaveBackend = () => {
    try {
      localStorage.setItem(STORAGE_KEYS.BACKEND_URL, backendUrl);
      setSaveStatus(true);
      setTimeout(() => setSaveStatus(false), 3000);
    } catch (error) {
      console.error(`Failed to save to localStorage: ${error instanceof Error ? error.message : 'Unknown error'}`);
      alert("Failed to save settings. Please ensure cookies/local storage are enabled.");
    }
  };

  useEffect(() => {
    let interval: NodeJS.Timeout;

    const fetchComfortData = async () => {
      if (activeTab !== "Room") return;

      try {
        const response = await fetch(`${backendUrl}/comfort`);
        if (!response.ok) {
          throw new Error(`Server responded with status: ${response.status}`);
        }
        const data = await response.json();
        
        // Defensive update: merge existing reading with valid numeric fields from response
        setReading(prev => ({
          ...prev,
          ...(typeof data.comfort === 'number' && { comfort: data.comfort }),
          ...(typeof data.occupancy === 'number' && { occupancy: data.occupancy }),
          ...(typeof data.queue === 'number' && { queue: data.queue }),
          ...(typeof data.sound === 'number' && { sound: data.sound }),
          ...(typeof data.crowd === 'number' && { crowd: data.crowd }),
          ...(typeof data.flow === 'number' && { flow: data.flow }),
        }));
      } catch (error) {
        // Requirements: Any error leaves previously displayed values unchanged.
        console.error(`Failed to fetch comfort data: ${error instanceof Error ? error.message : 'Unknown error'}`);
      }
    };

    if (activeTab === "Room" && backendUrl) {
      fetchComfortData();
      interval = setInterval(fetchComfortData, 5000);
    }

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [activeTab, backendUrl]);

  const comfortBand = getComfortBand(reading.comfort);

  const renderContent = () => {
    switch (activeTab) {
      case "Room":
        return <RoomView reading={reading} comfortBand={comfortBand} />;
      case "Activity":
        return <ActivityView activities={SAMPLE_ACTIVITY} />;
      case "Controls":
        return <ControlsView backendUrl={backendUrl} />;
      case "Settings":
        return (
          <SettingsView
            backendUrl={backendUrl}
            setBackendUrl={setBackendUrl}
            onSave={handleSaveBackend}
            saveStatus={saveStatus}
          />
        );
      default:
        throw new Error(`Unhandled tab state: ${activeTab}`);
    }
  };

  const tabs: Tab[] = ["Room", "Controls", "Activity", "Settings"];

  return (
    <div style={{ 
      backgroundColor: '#fdfaf5', 
      minHeight: '100vh', 
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
    }}>
      <div style={{ 
        maxWidth: '480px', 
        margin: '0 auto', 
        backgroundColor: '#fdfaf5',
        position: 'relative',
        minHeight: '100vh',
        paddingBottom: '80px',
        paddingTop: '60px'
      }}>
        {/* Fixed Header */}
        <header style={{ 
          position: 'fixed', 
          top: 0, 
          width: '100%', 
          maxWidth: '480px', 
          height: '60px', 
          backgroundColor: '#5d4037', 
          color: '#fff', 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
          zIndex: 1000
        }}>
          <h1 style={{ fontSize: '1.2rem', margin: 0 }}>Caffe Steve</h1>
        </header>

        {/* Main Content */}
        <main style={{ padding: '20px' }}>
          {renderContent()}
        </main>

        {/* Fixed Bottom Navigation */}
        <nav style={{ 
          position: 'fixed', 
          bottom: 0, 
          width: '100%', 
          maxWidth: '480px', 
          height: '70px', 
          backgroundColor: '#fff', 
          borderTop: '1px solid #eee', 
          display: 'flex', 
          justifyContent: 'space-around', 
          alignItems: 'center',
          zIndex: 1000
        }}>
          {tabs.map((tab) => (
            <button 
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                background: 'none',
                border: 'none',
                color: activeTab === tab ? '#5d4037' : '#a1887f',
                fontWeight: activeTab === tab ? 'bold' : 'normal',
                fontSize: '0.8rem',
                cursor: 'pointer',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '4px'
              }}
            >
              <div style={{ 
                width: '6px', 
                height: '6px', 
                borderRadius: '50%', 
                backgroundColor: activeTab === tab ? '#5d4037' : 'transparent' 
              }} />
              {tab}
            </button>
          ))}
        </nav>
      </div>
    </div>
  );
};

export default App;