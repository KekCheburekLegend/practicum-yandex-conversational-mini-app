import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from 'react';
import styles from './App.module.css';

const applications = [
  { id: 'research', name: 'Research Board', description: 'Утверждения, источники и доказательства' },
  { id: 'planner', name: 'Project Planner', description: 'Задачи, сроки и зависимости' },
  { id: 'explorer', name: 'Data Explorer', description: 'Данные, фильтры и сценарии what-if' },
] as const;
type AppId = typeof applications[number]['id'];
type Message = { id: string; role: 'user' | 'studio'; text: string; appId?: AppId };
type Conversation = { id: string; title: string; messages: Message[] };

function newConversation(): Conversation {
  return { id: crypto.randomUUID(), title: 'Новый диалог', messages: [] };
}

export function App() {
  const [conversations, setConversations] = useState<Conversation[]>(() => [newConversation()]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [activeApp, setActiveApp] = useState<AppId>('research');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [theme, setTheme] = useState('dark');
  const [accent, setAccent] = useState('#8b5cf6');
  const endOfMessages = useRef<HTMLDivElement>(null);
  const conversation = conversations.find(item => item.id === activeId) ?? conversations[0];
  const application = applications.find(item => item.id === activeApp)!;

  useEffect(() => {
    endOfMessages.current?.scrollIntoView({ block: 'nearest' });
  }, [conversation.id, conversation.messages.length]);

  function createConversation() {
    const next = newConversation();
    setConversations(items => [next, ...items]);
    setActiveId(next.id);
    setDraft('');
    setSidebarOpen(false);
  }

  function sendMessage(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    const messages: Message[] = [
      { id: crypto.randomUUID(), role: 'user', text },
      { id: crypto.randomUUID(), role: 'studio', appId: activeApp,
        text: `Выбрано приложение ${application.name}. Это демонстрация интерфейса. Подключение router и runtime будет добавлено отдельно.` },
    ];
    setConversations(items => items.map(item => item.id === conversation.id
      ? { ...item, title: item.messages.length ? item.title : text.slice(0, 48), messages: [...item.messages, ...messages] }
      : item));
    setDraft('');
  }

  return (
    <div className={`${styles.shell} ${theme === 'light' ? styles.light : ''}`}
      style={{ '--accent': accent } as CSSProperties}>
      <aside className={styles.rail} aria-label="Разделы Studio">
        <span className={styles.logo} aria-label="Studio">S</span>
        <button aria-label="Открыть чат" aria-pressed={!settingsOpen} onClick={() => setSettingsOpen(false)}>◈</button>
        <button aria-label="Настройки оформления" aria-pressed={settingsOpen} onClick={() => setSettingsOpen(true)}>⚙</button>
      </aside>
      <aside id="conversations" className={`${styles.sidebar} ${sidebarOpen ? styles.sidebarOpen : ''}`} aria-label="Диалоги">
        <div className={styles.sidebarHeading}><strong>Studio</strong>
          <button className={styles.closeSidebar} aria-label="Закрыть список диалогов" onClick={() => setSidebarOpen(false)}>×</button>
        </div>
        <button className={styles.newChat} onClick={createConversation}>＋ Новый диалог</button>
        <p className={styles.caption}>ДИАЛОГИ</p>
        <nav className={styles.conversations}>
          {conversations.map(item => <button key={item.id} title={item.title}
            aria-current={item.id === conversation.id ? 'page' : undefined}
            onClick={() => { setActiveId(item.id); setDraft(''); setSidebarOpen(false); setSettingsOpen(false); }}>
            <span>◻</span><span>{item.title}</span>
          </button>)}
        </nav>
        <p className={styles.sidebarNote}>История хранится в памяти вкладки до перезагрузки.</p>
        <footer>Conversational<br />Mini-App Studio</footer>
      </aside>
      <main className={styles.main}>
        <header className={styles.header}>
          <button className={styles.menuButton} aria-label="Список диалогов" aria-controls="conversations"
            aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(!sidebarOpen)}>☰</button>
          <nav className={styles.tabs} aria-label="Mini-app">
            {applications.map(item => <button key={item.id} aria-pressed={!settingsOpen && item.id === activeApp}
              onClick={() => { setActiveApp(item.id); setSettingsOpen(false); }}>{item.name}</button>)}
          </nav>
          <span className={styles.demo}>Демо</span>
        </header>
        {settingsOpen ? <section className={styles.settings} aria-labelledby="settings-title">
          <h1 id="settings-title">Персонализация</h1>
          <p>Оформление рабочего пространства</p>
          <fieldset><legend>Режим интерфейса</legend><div className={styles.choices}>
            <button aria-pressed={theme === 'dark'} onClick={() => setTheme('dark')}>☾ Тёмная</button>
            <button aria-pressed={theme === 'light'} onClick={() => setTheme('light')}>☀ Светлая</button>
          </div></fieldset>
          <fieldset><legend>Цвет темы</legend><div className={styles.choices}>
            {[['#8b5cf6', 'Фиолетовый'], ['#0891b2', 'Голубой'], ['#059669', 'Зелёный']].map(([color, name]) =>
              <button key={color} aria-pressed={accent === color} onClick={() => setAccent(color)}>
                <span style={{ color }}>●</span> {name}</button>)}
          </div></fieldset>
          <button className={styles.newChat} onClick={() => setSettingsOpen(false)}>Вернуться в чат</button>
        </section> : <div className={styles.workspace}>
          <section className={styles.chat} aria-label="Чат">
            <div className={styles.messages}>
              {conversation.messages.length === 0 && <div className={styles.welcome}>
                <span className={styles.welcomeIcon}>◈</span>
                <h1>С чего начнём?</h1>
                <p>Выберите mini-app и опишите задачу в чате.</p>
                <div className={styles.suggestions}>
                  {applications.map(item => <button key={item.id} onClick={() => {
                    setActiveApp(item.id);
                    setDraft(`Открыть ${item.name}`);
                  }}><strong>{item.name} ↗</strong><span>{item.description}</span></button>)}
                </div>
              </div>}
              <div role="log" aria-label="Сообщения" aria-live="polite" aria-relevant="additions">
                {conversation.messages.map(message => <article key={message.id}
                  className={`${styles.message} ${message.role === 'user' ? styles.userMessage : ''}`}>
                  <strong>{message.role === 'user' ? 'Вы' : 'Studio'}</strong>
                  <p>{message.text}</p>
                  {message.appId && <button onClick={() => setActiveApp(message.appId!)}>Показать mini-app ↗</button>}
                </article>)}
              </div>
              <div ref={endOfMessages} />
            </div>
            <form className={styles.composer} onSubmit={sendMessage}>
              <label htmlFor="message">Сообщение для {application.name}</label>
              <div><textarea id="message" value={draft} maxLength={4000} rows={2}
                onChange={event => setDraft(event.target.value)} placeholder="Опишите задачу…"
                onKeyDown={event => {
                  if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }} />
                <button type="submit" disabled={!draft.trim()} aria-label="Отправить сообщение">↑</button>
              </div>
              <small>Enter — отправить · Shift + Enter — новая строка</small>
            </form>
          </section>
          <section className={styles.appPanel} aria-labelledby="app-title">
            <div className={styles.panelHeading}><span>РАБОЧЕЕ ПРОСТРАНСТВО</span><span>◈</span></div>
            <h2 id="app-title">{application.name}</h2><p>{application.description}</p>
            <div className={styles.placeholder}><span>◈</span><h3>Место для mini-app</h3>
              <p>Здесь появится интерактивный интерфейс приложения после подключения runtime и Schema Renderer.</p>
            </div>
          </section>
        </div>}
        <p className={styles.disclaimer}>Самостоятельная платформа. Обязательная или официальная интеграция с ChatGPT/OpenAI отсутствует.</p>
      </main>
    </div>
  );
}
