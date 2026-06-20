import React from 'react';
import { AutopilotAction } from './types';

interface ActivityViewProps {
  activities: AutopilotAction[];
}

export const ActivityView: React.FC<ActivityViewProps> = ({ activities }) => (
  <section style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
    <h2 style={{ color: '#5d4037', marginBottom: '20px' }}>Recent Activity</h2>
    <div style={{ 
      display: 'flex', 
      flexDirection: 'column', 
      gap: '15px', 
      overflowY: 'auto',
      maxHeight: 'calc(100vh - 200px)',
      paddingRight: '5px'
    }}>
      {activities.map((action, index) => (
        <div 
          key={`${action.time}-${index}`} 
          style={{ 
            borderLeft: '4px solid #d7ccc8', 
            background: '#fff', 
            padding: '12px 15px', 
            borderRadius: '0 8px 8px 0',
            boxShadow: '0 2px 4px rgba(0,0,0,0.02)'
          }}
        >
          <div style={{ color: '#8d6e63', fontSize: '0.75rem', fontWeight: 'bold', marginBottom: '4px' }}>
            {action.time}
          </div>
          <div style={{ fontWeight: 'bold', fontSize: '1rem', color: '#5d4037', marginBottom: '2px' }}>
            {action.title}
          </div>
          <div style={{ fontSize: '0.85rem', color: '#a1887f' }}>
            {action.reason}
          </div>
        </div>
      ))}
    </div>
  </section>
);

interface SettingsViewProps {
  backendUrl: string;
  setBackendUrl: (url: string) => void;
  onSave: () => void;
  saveStatus: boolean;
  blobId?: string;
}

export const SettingsView: React.FC<SettingsViewProps> = ({ 
  backendUrl, 
  setBackendUrl, 
  onSave, 
  saveStatus,
  blobId = (typeof localStorage !== 'undefined' && localStorage.getItem('gc_blob')) || 'demo-snapshot'
}) => (
  <section style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
    <h2 style={{ color: '#5d4037' }}>Settings</h2>
    <div style={{ background: '#fff', padding: '20px', borderRadius: '8px', boxShadow: '0 2px 4px rgba(0,0,0,0.05)' }}>
      <div style={{ marginBottom: '15px' }}>
        <label 
          htmlFor="backend-url" 
          style={{ display: 'block', marginBottom: '8px', fontWeight: 'bold', fontSize: '0.9rem', color: '#5d4037' }}
        >
          Café Backend URL
        </label>
        <input
          id="backend-url"
          type="text"
          value={backendUrl}
          onChange={(e) => setBackendUrl(e.target.value)}
          style={{
            width: '100%',
            padding: '10px',
            borderRadius: '4px',
            border: '1px solid #d7ccc8',
            fontSize: '0.9rem',
            boxSizing: 'border-box'
          }}
        />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <button
          onClick={onSave}
          style={{
            backgroundColor: '#5d4037',
            color: 'white',
            border: 'none',
            padding: '10px 20px',
            borderRadius: '4px',
            cursor: 'pointer',
            fontWeight: 'bold'
          }}
        >
          Save
        </button>
        {saveStatus && (
          <span style={{ color: '#4caf50', fontSize: '0.85rem', fontWeight: 'bold' }}>
            ✓ Saved
          </span>
        )}
      </div>
    </div>

    <div style={{ background: '#fff', padding: '20px', borderRadius: '8px', boxShadow: '0 2px 4px rgba(0,0,0,0.05)' }}>
      <h3 style={{ color: '#5d4037', marginTop: 0, fontSize: '1.1rem' }}>Tamper-proof record</h3>
      <p style={{ fontSize: '0.85rem', color: '#795548', lineHeight: '1.4', marginBottom: '15px' }}>
        The autopilot's action history is anchored to Walrus decentralized storage so it can be independently verified.
      </p>
      <button
        onClick={() => window.open(`https://aggregator.walrus-testnet.walrus.space/v1/blobs/${blobId}`, '_blank')}
        style={{
          backgroundColor: '#8d6e63',
          color: 'white',
          border: 'none',
          padding: '10px 15px',
          borderRadius: '4px',
          cursor: 'pointer',
          fontWeight: 'bold',
          fontSize: '0.85rem'
        }}
      >
        Verify latest snapshot
      </button>
    </div>
  </section>
);