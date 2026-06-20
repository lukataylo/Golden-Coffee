import React from 'react';
import { Reading, Alert, ComfortBand } from './types';

interface RoomViewProps {
  reading: Reading;
  band: ComfortBand;
}

export const RoomView: React.FC<RoomViewProps> = ({ reading, band }) => (
  <section style={{ textAlign: 'center' }}>
    <div style={{ margin: '20px 0 40px' }}>
      <h2 style={{ fontSize: '3rem', margin: '0', color: '#333' }}>
        {reading.comfort} <span style={{ fontSize: '1.2rem', color: '#999' }}>/ 100</span>
      </h2>
      <p style={{ fontSize: '1.2rem', fontWeight: 'bold', margin: '5px 0', color: '#666' }}>{band}</p>
    </div>

    <div style={{ display: 'flex', gap: '15px' }}>
      <div style={{ flex: 1, padding: '20px', backgroundColor: '#fff', borderRadius: '12px', boxShadow: '0 2px 8px rgba(0,0,0,0.05)' }}>
        <div style={{ fontSize: '1.5rem', fontWeight: 'bold' }}>{reading.occupancy}</div>
        <div style={{ fontSize: '0.8rem', color: '#888', textTransform: 'uppercase' }}>In room</div>
      </div>
      <div style={{ flex: 1, padding: '20px', backgroundColor: '#fff', borderRadius: '12px', boxShadow: '0 2px 8px rgba(0,0,0,0.05)' }}>
        <div style={{ fontSize: '1.5rem', fontWeight: 'bold' }}>{reading.queue}</div>
        <div style={{ fontSize: '0.8rem', color: '#888', textTransform: 'uppercase' }}>In queue</div>
      </div>
    </div>
  </section>
);

interface AlertsViewProps {
  alerts: Alert[];
}

export const AlertsView: React.FC<AlertsViewProps> = ({ alerts }) => (
  <section style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
    <h2 style={{ marginBottom: '16px' }}>Recent Alerts</h2>
    <div style={{ 
      overflowY: 'auto', 
      flex: 1,
      paddingRight: '4px'
    }}>
      {alerts.map((alert, index) => (
        <div 
          key={index} 
          style={{ 
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            padding: '16px',
            backgroundColor: '#fff',
            borderRadius: '12px',
            marginBottom: '12px',
            boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
          }}
        >
          <span style={{ fontSize: '0.85rem', color: '#888', whiteSpace: 'nowrap', width: '45px' }}>
            {alert.time}
          </span>
          <span style={{ 
            height: '10px', 
            width: '10px', 
            borderRadius: '50%', 
            backgroundColor: alert.level === 'warn' ? '#f0ad4e' : '#bdc3c7',
            flexShrink: 0
          }} title={alert.level} />
          <span style={{ fontSize: '0.95rem', color: '#333', lineHeight: '1.4' }}>
            {alert.message}
          </span>
        </div>
      ))}
    </div>
  </section>
);

interface SettingsViewProps {
  backendUrl: string;
  setBackendUrl: (url: string) => void;
  onSave: () => void;
  showSavedFeedback: boolean;
}

export const SettingsView: React.FC<SettingsViewProps> = ({ 
  backendUrl, 
  setBackendUrl, 
  onSave, 
  showSavedFeedback 
}) => (
  <section>
    <h2 style={{ marginBottom: '20px' }}>Settings</h2>
    <div style={{ backgroundColor: '#fff', padding: '20px', borderRadius: '12px', boxShadow: '0 2px 8px rgba(0,0,0,0.05)' }}>
      <label htmlFor="backend-url" style={{ display: 'block', fontSize: '0.8rem', color: '#888', textTransform: 'uppercase', marginBottom: '8px', fontWeight: 'bold' }}>
        Café Backend URL
      </label>
      <input
        id="backend-url"
        type="text"
        value={backendUrl}
        onChange={(e) => setBackendUrl(e.target.value)}
        style={{
          width: '100%',
          padding: '12px',
          borderRadius: '6px',
          border: '1px solid #ddd',
          fontSize: '14px',
          boxSizing: 'border-box',
          marginBottom: '16px'
        }}
      />
      <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
        <button 
          onClick={onSave}
          style={{
            backgroundColor: '#d9534f',
            color: 'white',
            border: 'none',
            padding: '10px 20px',
            borderRadius: '6px',
            fontWeight: 'bold',
            cursor: 'pointer'
          }}
        >
          Save
        </button>
        {showSavedFeedback && (
          <span style={{ color: '#5cb85c', fontWeight: 'bold', fontSize: '0.9rem' }}>
            Saved
          </span>
        )}
      </div>
    </div>
  </section>
);