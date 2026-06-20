import React, { useState, useEffect, useMemo } from 'react';
import { SAMPLE_READING, SAMPLE_ALERTS, STORAGE_KEYS, DEFAULT_BACKEND_URL } from './constants';
import { getComfortBand, fetchReading } from './utils';
import { RoomView, AlertsView, SettingsView } from './components';
import { Reading } from './types';

type Tab = "Room" | "Alerts" | "Settings";

const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<Tab>("Room");
  const [backendUrl, setBackendUrl] = useState<string>(() => {
    return localStorage.getItem(STORAGE_KEYS.BACKEND_URL) || DEFAULT_BACKEND_URL;
  });
  const [showSavedFeedback, setShowSavedFeedback] = useState(false);
  const [currentReading, setCurrentReading] = useState<Reading>(SAMPLE_READING);

  const band = useMemo(() => getComfortBand(currentReading.comfort), [currentReading.comfort]);

  useEffect(() => {
    if (activeTab !== "Room") return;

    const updateReading = async () => {
      const data = await fetchReading(backendUrl);
      if (data) {
        setCurrentReading(data);
      }
    };

    updateReading();
    const intervalId = setInterval(updateReading, 5000);

    return () => clearInterval(intervalId);
  }, [activeTab, backendUrl]);

  const handleSaveSettings = () => {
    try {
      localStorage.setItem(STORAGE_KEYS.BACKEND_URL, backendUrl);
      setShowSavedFeedback(true);
      setTimeout(() => setShowSavedFeedback(false), 2000);
    } catch (error) {
      console.error(`Failed to save to localStorage: ${error}`);
      alert("Error saving settings. Please check your browser permissions.");
    }
  };

  const containerStyle: React.CSSProperties = {
    maxWidth: '480px',
    margin: '0 auto',
    minHeight: '100vh',
    backgroundColor: '#fdfaf6',
    fontFamily: 'sans-serif',
    position: 'relative',
    display: 'flex',
    flexDirection: 'column'
  };

  const headerStyle: React.CSSProperties = {
    position: 'fixed',
    top: 0,
    width: '100%',
    maxWidth: '480px',
    height: '60px',
    backgroundColor: '#fff',
    borderBottom: '1px solid #eee',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000
  };

  const footerStyle: React.CSSProperties = {
    position: 'fixed',
    bottom: 0,
    width: '100%',
    maxWidth: '480px',
    height: '60px',
    backgroundColor: '#fff',
    borderTop: '1px solid #eee',
    display: 'flex',
    zIndex: 1000
  };

  const contentStyle: React.CSSProperties = {
    padding: '80px 20px 80px 20px',
    flex: 1
  };

  const tabButtonStyle = (tab: Tab): React.CSSProperties => ({
    flex: 1,
    border: 'none',
    background: 'none',
    fontSize: '14px',
    fontWeight: activeTab === tab ? 'bold' : 'normal',
    color: activeTab === tab ? '#d9534f' : '#666',
    cursor: 'pointer'
  });

  return (
    <div style={containerStyle}>
      <header style={headerStyle}>
        <h1 style={{ fontSize: '1.2rem', margin: 0 }}>Golden Coffee</h1>
      </header>

      <main style={contentStyle}>
        {activeTab === "Room" && <RoomView reading={currentReading} band={band} />}
        {activeTab === "Alerts" && <AlertsView alerts={SAMPLE_ALERTS} />}
        {activeTab === "Settings" && (
          <SettingsView 
            backendUrl={backendUrl} 
            setBackendUrl={setBackendUrl} 
            onSave={handleSaveSettings} 
            showSavedFeedback={showSavedFeedback} 
          />
        )}
      </main>

      <nav style={footerStyle}>
        <button style={tabButtonStyle("Room")} onClick={() => setActiveTab("Room")}>Room</button>
        <button style={tabButtonStyle("Alerts")} onClick={() => setActiveTab("Alerts")}>Alerts</button>
        <button style={tabButtonStyle("Settings")} onClick={() => setActiveTab("Settings")}>Settings</button>
      </nav>
    </div>
  );
};

export default App;