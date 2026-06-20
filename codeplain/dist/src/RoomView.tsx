import React from 'react';
import { Reading, ComfortBand } from './types';

interface RoomViewProps {
  reading: Reading;
  comfortBand: ComfortBand;
}

export const RoomView: React.FC<RoomViewProps> = ({ reading, comfortBand }) => (
  <section style={{ textAlign: 'center', padding: '20px 0' }}>
    <div style={{ marginBottom: '40px' }}>
      <div style={{ fontSize: '3.5rem', fontWeight: 'bold', color: '#5d4037', lineHeight: 1 }}>
        {reading.comfort}<span style={{ fontSize: '1.2rem', opacity: 0.6 }}> / 100</span>
      </div>
      <div style={{ 
        fontSize: '1.1rem', 
        fontWeight: '600', 
        color: '#8d6e63', 
        marginTop: '8px',
        textTransform: 'uppercase',
        letterSpacing: '0.05em'
      }}>
        {comfortBand}
      </div>
    </div>

    <div style={{ 
      display: 'flex', 
      justifyContent: 'space-around', 
      background: '#fff', 
      padding: '20px', 
      borderRadius: '12px', 
      boxShadow: '0 2px 8px rgba(0,0,0,0.05)',
      marginBottom: '30px'
    }}>
      <div>
        <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#5d4037' }}>{reading.occupancy}</div>
        <div style={{ fontSize: '0.8rem', color: '#a1887f', marginTop: '4px' }}>In room</div>
      </div>
      <div style={{ width: '1px', backgroundColor: '#efebe9' }} />
      <div>
        <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#5d4037' }}>{reading.queue}</div>
        <div style={{ fontSize: '0.8rem', color: '#a1887f', marginTop: '4px' }}>In queue</div>
      </div>
    </div>

    <div style={{ textAlign: 'left', padding: '0 10px' }}>
      <h3 style={{ fontSize: '0.9rem', color: '#8d6e63', marginBottom: '15px', textTransform: 'uppercase' }}>Comfort breakdown</h3>
      {[
        { label: 'Sound', value: reading.sound },
        { label: 'Crowd', value: reading.crowd },
        { label: 'Flow', value: reading.flow }
      ].map((item) => (
        <div key={item.label} style={{ marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '15px' }}>
          <div style={{ width: '60px', fontSize: '0.85rem', color: '#5d4037', fontWeight: '500' }}>{item.label}</div>
          <div style={{ flex: 1, height: '8px', backgroundColor: '#efebe9', borderRadius: '4px', overflow: 'hidden' }}>
            <div style={{ 
              width: `${Math.min(Math.max(item.value, 0), 100)}%`, 
              height: '100%', 
              backgroundColor: '#a1887f', 
              borderRadius: '4px' 
            }} />
          </div>
          <div style={{ width: '30px', fontSize: '0.85rem', color: '#5d4037', textAlign: 'right' }}>{item.value}</div>
        </div>
      ))}
    </div>
  </section>
);