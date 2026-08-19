import { useState, useEffect, useRef, useCallback } from 'react';
import { IconSettings2, IconX, IconHeartFilled, IconBug, IconAlertTriangle, IconChevronDown, IconHash } from '@tabler/icons-react';
import { settingsStore } from '../lib/store';
import type { AppSettings } from '../lib/types';
import { SetAutoStart, GetAutoStart, GetVersion, GenerateReport, GetObfsAccepted, SetObfsAccepted, SetObfsMode } from '../../wailsjs/go/backend/App';
import { BrowserOpenURL } from '../../wailsjs/runtime/runtime';
import { logStore } from '../lib/stores/logStore';
import { toastStore } from '../lib/stores/toastStore';
import './Settings.css';

interface Props {
  onClose: () => void;
}

const EMPTY_HASHES: [string, string, string, string] = ['', '', '', ''];

export default function Settings({ onClose }: Props) {
  const [settings, setSettings] = useState<AppSettings>(() => settingsStore.get());
  const [version, setVersion] = useState('...');
  const [hashesOpen, setHashesOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const copiedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [showObfsModal, setShowObfsModal] = useState(false);
  const [pendingObfsMode, setPendingObfsMode] = useState<'audio' | 'video'>('audio');
  const [copiedReport, setCopiedReport] = useState(false);

  const update = useCallback(<K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setSettings(s => {
      const next = { ...s, [key]: value };
      settingsStore.save(next);
      return next;
    });
  }, []);

  useEffect(() => {
    return () => { if (copiedTimerRef.current) clearTimeout(copiedTimerRef.current); };
  }, []);

  useEffect(() => {
    GetAutoStart().then(v => {
      if (v !== settings.autoStart) update('autoStart', v);
    }).catch(() => { toastStore.show('Не удалось загрузить настройки', 3000); });
    GetObfsAccepted().then(v => update('obfsAccepted', v)).catch(() => {});
    GetVersion().then(setVersion).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleReport = async () => {
    const logs = logStore.getAll();
    const report = await GenerateReport(logs.map(e => ({
      level: e.level,
      message: e.message,
      time: e.time,
      count: e.count,
    })));
    const mode = settings.obfsMode || 'audio';
    const accepted = settings.obfsAccepted ? 'да' : 'нет';
    const full = report + `\n## Settings\n- Obfuscation: ${mode}\n- Obfs accepted: ${accepted}\n- Auto connect: ${settings.autoConnect ? 'yes' : 'no'}\n- Global hashes: ${settings.useGlobalHashes ? 'yes' : 'no'}\n`;
    await navigator.clipboard.writeText(full);
    setCopiedReport(true);
    if (copiedTimerRef.current) clearTimeout(copiedTimerRef.current);
    copiedTimerRef.current = setTimeout(() => setCopiedReport(false), 2000);
  };

  const handleObfsClick = async (mode: 'audio' | 'video') => {
    if (settings.obfsAccepted) {
      update('obfsMode', mode);
      await SetObfsMode(mode);
    } else {
      setPendingObfsMode(mode);
      setShowObfsModal(true);
    }
  };

  const handleObfsAccept = async () => {
    try {
      await SetObfsAccepted(true);
      await SetObfsMode(pendingObfsMode);
      update('obfsAccepted', true);
      update('obfsMode', pendingObfsMode);
      setShowObfsModal(false);
    } catch {
      toastStore.show('Не удалось сохранить настройки', 3000);
    }
  };

  const globalHashes = settings.globalHashes ?? EMPTY_HASHES;
  const hashCount = globalHashes.filter(h => h.trim()).length;

  const setHash = (index: number, value: string) => {
    const next: [string, string, string, string] = [...globalHashes] as [string, string, string, string];
    next[index] = value.trim();
    update('globalHashes', next);
  };

  return (
    <>
      <div className="st-overlay" onClick={onClose}>
        <div className="st-modal st-modal--full" onClick={e => e.stopPropagation()}>
          <div className="st-header">
            <IconSettings2 stroke={2} size={20} />
            <span className="st-title">Настройки</span>
            <button type="button" className="st-close" onClick={onClose} aria-label="Закрыть"><IconX size={18} /></button>
          </div>

          <div className="st-power-block">
            <div>
              <div className="st-power-title">Мощность</div>
              <div className="st-power-sub">Настраивается в редакторе профиля</div>
            </div>
            <span className="st-power-value">профиль</span>
          </div>

          <div className="st-row">
            <span>Трей</span>
            <button type="button" className={`st-toggle st-toggle--${settings.trayEnabled ? 'on' : 'off'}`} onClick={() => update('trayEnabled', !settings.trayEnabled)} />
          </div>

          <div className="st-row">
            <span>Запускать при старте</span>
            <button type="button" className={`st-toggle st-toggle--${settings.autoStart ? 'on' : 'off'}`} onClick={() => {
              const next = !settings.autoStart;
              update('autoStart', next);
              void SetAutoStart(next);
            }} />
          </div>

          <div className="st-row">
            <span>Авто-подключение</span>
            <button type="button" className={`st-toggle st-toggle--${settings.autoConnect ? 'on' : 'off'}`} onClick={() => update('autoConnect', !settings.autoConnect)} />
          </div>

          <div className="st-row">
            <span>Глобальные хэши</span>
            <button type="button" className={`st-toggle st-toggle--${settings.useGlobalHashes ? 'on' : 'off'}`} onClick={() => update('useGlobalHashes', !settings.useGlobalHashes)} />
          </div>

          <button type="button" className="st-hash-box" onClick={() => setHashesOpen(v => !v)}>
            <IconHash size={17} />
            <span>VK Хеши ({hashCount}/4)</span>
            <IconChevronDown size={16} className={hashesOpen ? 'st-chevron st-chevron--open' : 'st-chevron'} />
          </button>

          {hashesOpen && (
            <div className="st-hash-editor">
              {[0, 1, 2, 3].map(i => (
                <input
                  key={i}
                  className="st-hash-input"
                  value={globalHashes[i] ?? ''}
                  onChange={e => setHash(i, e.target.value)}
                  placeholder={`VK hash ${i + 1}`}
                  spellCheck={false}
                />
              ))}
              <div className="st-hash-note">При включённых «Глобальных хэшах» эти значения используются вместо хэшей выбранного профиля.</div>
            </div>
          )}

          <button type="button" className="st-advanced-head" onClick={() => setAdvancedOpen(v => !v)}>
            <span>Расширенные</span>
            <IconChevronDown size={17} className={advancedOpen ? 'st-chevron st-chevron--open' : 'st-chevron'} />
          </button>

          {advancedOpen && (
            <div className="st-advanced-body">
              <div className="st-row st-row--advanced">
                <span>Режим обфускации {!settings.obfsAccepted && <span className="st-badge">только latest</span>}</span>
                <div className="st-segment">
                  <button type="button" className={`st-seg-btn${settings.obfsMode === 'audio' ? ' st-seg-btn--active' : ''}`} onClick={() => handleObfsClick('audio')}>Audio</button>
                  <button type="button" className={`st-seg-btn${settings.obfsMode === 'video' ? ' st-seg-btn--active' : ''}`} onClick={() => handleObfsClick('video')}>Video</button>
                </div>
              </div>

              <div className="st-info">
                <div className="st-info-name">OBhoD</div>
                <div className="st-info-ver">v{version}</div>
              </div>

              <div className="st-actions">
                <button type="button" className={`st-action${copiedReport ? ' st-action--copied' : ''}`} onClick={handleReport}>
                  <IconBug size={14} />
                  {copiedReport ? 'Скопировано!' : 'Отчёт'}
                </button>
              </div>

              <button type="button" className="st-donate" onClick={() => BrowserOpenURL('https://test-36.ru/connect')}>
                <IconHeartFilled size={16} />
                Поддержать проект / Оплата Брони
              </button>
            </div>
          )}
        </div>
      </div>

      {showObfsModal && (
        <div className="st-overlay" onClick={() => setShowObfsModal(false)}>
          <div className="st-modal st-obfs-modal" onClick={e => e.stopPropagation()}>
            <div className="st-obfs-icon"><IconAlertTriangle size={32} /></div>
            <div className="st-obfs-title">Режим обфускации</div>
            <div className="st-obfs-text">Обфускация поддерживается только на последней версии сервера WDTT. На старых серверах соединение может не состояться.</div>
            <div className="st-obfs-text st-obfs-disclaimer">Если не уверены в совместимости, используйте Audio.</div>
            <div className="st-obfs-actions">
              <button type="button" className="st-obfs-btn st-obfs-btn--cancel" onClick={() => setShowObfsModal(false)}>Отмена</button>
              <button type="button" className="st-obfs-btn st-obfs-btn--accept" onClick={handleObfsAccept}>Принимаю</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
