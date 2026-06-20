import React, { useState } from 'react';
import { ControlCategory, ControlAction } from './types';

export * from './views';
export * from './RoomView';

interface ControlsViewProps {
  backendUrl: string;
}

export const ControlsView: React.FC<ControlsViewProps> = ({ backendUrl }) => {
  const [confirmations, setConfirmations] = useState<Record<string, string>>({});

  const handleNudge = async (control: ControlCategory, action: ControlAction) => {
    // Optimistic update
    setConfirmations(prev => ({ ...prev, [control]: action }));

    try {
      const response = await fetch(`${backendUrl}/override`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ control, action })
      });

      if (!response.ok) {
        console.error(`Nudge failed for ${control}: ${response.status} ${response.statusText}`);
      }
    } catch (error) {
      console.error(`Nudge network error for ${control}:`, error);
    }
  };

  const controlCards: { title: string; key: ControlCategory; actions: ControlAction[] }[] = [
    { title: "Music", key: "music", actions: ["quieter", "louder"] },
    { title: "Lighting", key: "lighting", actions: ["warmer", "brighter"] },
    { title: "Scent", key: "scent", actions: ["on", "off"] }
  ];

  return (
    <section>
      <h2 style={{ color: '#5d4037', marginBottom: '20px' }}>Nudge Room</h2>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
        {controlCards.map((card) => (
          <div key={card.key} style={{ background: '#fff', padding: '20px', borderRadius: '12px', boxShadow: '0 2px 8px rgba(0,0,0,0.05)' }}>
            <h3 style={{ margin: '0 0 15px 0', fontSize: '1.1rem', color: '#5d4037' }}>{card.title}</h3>
            <div style={{ display: 'flex', gap: '10px', marginBottom: confirmations[card.key] ? '12px' : '0' }}>
              {card.actions.map((action) => (
                <button
                  key={action}
                  onClick={() => handleNudge(card.key, action)}
                  style={{
                    flex: 1,
                    padding: '10px',
                    borderRadius: '6px',
                    border: '1px solid #d7ccc8',
                    background: '#fdfaf5',
                    color: '#5d4037',
                    fontWeight: 'bold',
                    textTransform: 'capitalize',
                    cursor: 'pointer'
                  }}
                >
                  {action}
                </button>
              ))}
            </div>
            {confirmations[card.key] && (
              <div style={{ fontSize: '0.85rem', color: '#8d6e63', fontStyle: 'italic' }}>
                Sent: {confirmations[card.key]}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
};