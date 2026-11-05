import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, ArrowDownToLine, ArrowRight, BookOpen, Check, CircleHelp, ClipboardList, DoorOpen, KeyRound, LogIn, Plus, RefreshCw, Send, ShieldCheck, Sparkles, X } from 'lucide-react';
import './styles.css';

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'include',                                                                             //Без этого флага браузер не отправит сессию на сервер и будет только 401
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) throw new ApiError(response.status, body?.detail || 'Не удалось выполнить запрос');
  return body;
}

function App() {                                            //Хранилище состояния (State)
  const [user, setUser] = useState(null);                   //Текущий пользователь (null = не авторизован)
  const [loading, setLoading] = useState(true);
  const [surveys, setSurveys] = useState([]);               //Список опросов
  const [selectedId, setSelectedId] = useState(null);       //ID выбранного опроса
  const [surveyDetails, setSurveyDetails] = useState(null);
  const [ratings, setRatings] = useState({ rating_materials: 4, rating_clarity: 4, rating_engagement: 4 });
  const [results, setResults] = useState(null);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [login, setLogin] = useState({ username: '', password: '' });
  const [resetMode, setResetMode] = useState(false);
  const [reset, setReset] = useState({ username: '', token: '', new_password: '' });
  const [newSurvey, setNewSurvey] = useState({ subject_id: '1', teacher_id: '1', period_start: new Date().toISOString().slice(0, 10), period_end: `${new Date().getFullYear()}-12-31` });

  async function loadSurveys(currentUser = user) {
    if (!currentUser) return;
    setBusy(true);
    try {
      const data = await api('/api/v1/surveys?limit=100');
      setSurveys(data.items);
      if (currentUser.role === 'student' && selectedId && !data.items.some((item) => item.id === selectedId)) {
        setSelectedId(null);
        setSurveyDetails(null);
      }
      setNotice('');
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {                             //Загрузка сессии при старте
    api('/api/v1/auth/me')
      .then((currentUser) => {
        setUser(currentUser);                   //Если куки живы, сервер вернет данные
        return loadSurveys(currentUser);
      })
      .catch(() => {})                          //401 - ничего
      .finally(() => setLoading(false));
  }, []);

  async function openSurvey(surveyId) {
    setSelectedId(surveyId);
    setResults(null);
    try {
      const data = await api(`/api/v1/surveys/${surveyId}`);
      setSurveyDetails(data);
      setNotice('');
    } catch (error) {
      setSurveyDetails(null);
      setNotice(error.message);
    }
  }

  async function signIn(event) {      //Вход
    event.preventDefault();           //Отменяем перезагрузку страницы формой
    setBusy(true);
    try {
      const currentUser = await api('/api/v1/auth/login', { method: 'POST', body: JSON.stringify(login) });
      setUser(currentUser);
      setLogin({ username: '', password: '' });
      setNotice('');
      await loadSurveys(currentUser);
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
      setLoading(false);
    }
  }

  async function signOut() {      //Выход
    await api('/api/v1/auth/logout', { method: 'POST' });
    setUser(null);
    setSurveys([]);
    setSelectedId(null);
    setSurveyDetails(null);
    setResults(null);
    setNotice('Вы вышли из системы');
  }

  async function submitVote(event) {      //Голосование
    event.preventDefault();
    if (!selectedId) return;
    setBusy(true);
    try {
      await api(`/api/v1/surveys/${selectedId}/responses`, { method: 'POST', body: JSON.stringify(ratings) });
      setNotice('Оценки приняты. Ответ не содержит вашего идентификатора.');
      await openSurvey(selectedId);     //Перезапрашиваем опрос, чтобы обновить флаг own_mark
      await loadSurveys();
    } catch (error) {
      setNotice(error.message);         //Уже голосовали" (409) или "Опрос закрыт" (410)
    } finally {
      setBusy(false);
    }
  }

  async function createSurvey(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const created = await api('/api/v1/surveys', {
        method: 'POST',
        body: JSON.stringify({ ...newSurvey, subject_id: Number(newSurvey.subject_id), teacher_id: Number(newSurvey.teacher_id) }),
      });
      setNotice(`Опрос №${created.id} создан как черновик`);
      await loadSurveys();
      await openSurvey(created.id).catch(() => {});
    } catch (error) {                     
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function changeStatus(survey, status) {
    setBusy(true);
    try {
      await api(`/api/v1/surveys/${survey.id}/status`, { method: 'PATCH', body: JSON.stringify({ status }) });
      setNotice(status === 'closed' ? 'Опрос закрыт. Задача отправлена в очередь.' : 'Опрос опубликован');
      await loadSurveys();
      await openSurvey(survey.id);
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function loadResults(surveyId) {
    setBusy(true);
    try {
      const data = await api(`/api/v1/surveys/${surveyId}/results`);
      setResults(data);
      setNotice('');
    } catch (error) {
      setResults(null);
      setNotice(error.status === 409 ? 'Агрегаты откроются после закрытия опроса и получения не менее пяти ответов.' : error.message);  //Если 409, то выдаём ответ
    } finally {
      setBusy(false);
    }
  }

  function downloadResults() {              //Скачивание CSV (Без участия сервера). Сервер отдал Json с агрегатами
    if (!results) return;
    const rows = [
      ['survey_id', results.survey_id],
      ['responses_count', results.responses_count],
      ['avg_materials', results.avg_materials],
      ['avg_clarity', results.avg_clarity],
      ['avg_engagement', results.avg_engagement],
    ];
    const blob = new Blob([rows.map((row) => row.join(',')).join('\n')], { type: 'text/csv;charset=utf-8' }); //Фронтенд формирует Blob в памяти браузера
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `survey-${results.survey_id}-results.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  async function requestReset(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const data = await api('/api/v1/auth/password-reset/request', { method: 'POST', body: JSON.stringify({ username: reset.username }) });
      setNotice(`${data.message}. В локальном режиме ссылка записана в журнал контейнера auth-service.`);
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmReset(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const data = await api('/api/v1/auth/password-reset/confirm', { method: 'POST', body: JSON.stringify({ token: reset.token, new_password: reset.new_password }) });
      setNotice(data.message);
      setResetMode(false);
      setReset({ username: '', token: '', new_password: '' });
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <main className="loading-screen"><span className="loader" />Загрузка рабочего пространства</main>;

  if (!user) {
    return (
      <main className="auth-layout">
        <section className="auth-intro">
          <div className="brand"><span className="brand-mark"><Activity size={20} /></span><span>ПОЛЕ / ОЦЕНКИ</span></div>
          <div className="intro-copy">
            <p className="eyebrow">АНОНИМНОЕ АНКЕТИРОВАНИЕ · 2026</p>
            <h1>Хорошее<br />преподавание<br /><em>видно в цифрах.</em></h1>
            <p className="intro-note">Три оценки. Ни одного свободного комментария. Ответы отделены от учётных записей.</p>
          </div>
          <div className="intro-footer"><ShieldCheck size={16} /> Сессия хранится в защищённой cookie</div>
        </section>
        <section className="auth-panel">
          <div className="auth-form-wrap">
            <div className="section-index">{resetMode ? 'ВОССТАНОВЛЕНИЕ' : 'ВХОД В СИСТЕМУ'} <span>01 / 01</span></div>
            {resetMode ? (
              <>
                <h2>Вернуть доступ</h2>
                <p className="muted">Код одноразовый и действует 15 минут. В этой локальной сборке письмо появляется в журнале сервиса.</p>
                <form onSubmit={requestReset} className="form-stack">
                  <label>Логин<input autoComplete="username" value={reset.username} onChange={(event) => setReset({ ...reset, username: event.target.value })} required /></label>
                  <button className="button button-dark" disabled={busy}>Отправить ссылку <ArrowRight size={16} /></button>
                </form>
                <form onSubmit={confirmReset} className="form-stack reset-confirm">
                  <label>Одноразовый код<input value={reset.token} onChange={(event) => setReset({ ...reset, token: event.target.value })} minLength={32} required /></label>
                  <label>Новый пароль<input type="password" autoComplete="new-password" value={reset.new_password} onChange={(event) => setReset({ ...reset, new_password: event.target.value })} minLength={12} required /></label>
                  <button className="button button-outline" disabled={busy}>Сменить пароль <KeyRound size={16} /></button>
                </form>
                <button className="text-button" onClick={() => setResetMode(false)}>← Вернуться ко входу</button>
              </>
            ) : (
              <>
                <h2>Войти в кабинет</h2>
                <p className="muted">Используйте выданную учётную запись студента или сотрудника.</p>
                <form onSubmit={signIn} className="form-stack">
                  <label>Логин<input autoComplete="username" value={login.username} onChange={(event) => setLogin({ ...login, username: event.target.value })} required /></label>
                  <label>Пароль<input type="password" autoComplete="current-password" value={login.password} onChange={(event) => setLogin({ ...login, password: event.target.value })} required /></label>
                  <button className="button button-dark" disabled={busy}>Войти <LogIn size={16} /></button>
                </form>
                <button className="text-button" onClick={() => setResetMode(true)}>Не удаётся войти? Восстановить доступ</button>
              </>
            )}
            {notice && <div className="notice" role="status">{notice}<button aria-label="Закрыть уведомление" onClick={() => setNotice('')}><X size={15} /></button></div>}
          </div>
          <div className="auth-bottom"><span>СЕРВИС КАЧЕСТВА ОБУЧЕНИЯ</span><span>© СПБПУ · 2026</span></div>
        </section>
      </main>
    );
  }

  const selected = surveys.find((survey) => survey.id === selectedId);
  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark"><Activity size={19} /></span><span>ПОЛЕ / ОЦЕНКИ</span></div>
        <div className="topbar-right"><span className="role-label">{user.role === 'staff' ? 'СОТРУДНИК' : 'СТУДЕНТ'}</span><span className="user-name">{user.username}</span><button className="icon-button" title="Выйти" aria-label="Выйти" onClick={signOut}><DoorOpen size={18} /></button></div>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <div className="sidebar-heading"><div><span className="eyebrow">РАБОЧАЯ ОБЛАСТЬ</span><h2>{user.role === 'staff' ? 'Управление' : 'Мои анкеты'}</h2></div><span className="count-badge">{surveys.length.toString().padStart(2, '0')}</span></div>
          <button className="refresh-button" onClick={() => loadSurveys()} disabled={busy}><RefreshCw size={14} className={busy ? 'spin' : ''} /> Обновить список</button>
          <div className="survey-list">
            {surveys.map((survey, index) => (
              <button className={`survey-row ${selectedId === survey.id ? 'selected' : ''}`} key={survey.id} onClick={() => openSurvey(survey.id)}>
                <span className="survey-number">{String(index + 1).padStart(2, '0')}</span>
                <span className="survey-row-copy"><strong>{survey.teacher_name}</strong><small>Дисциплина #{survey.subject_id} · №{survey.id}</small></span>
                <span className={`status-dot ${survey.status}`} title={survey.status} />
              </button>
            ))}
            {surveys.length === 0 && <p className="empty-small">Здесь пока нет доступных опросов.</p>}
          </div>
          <div className="privacy-note"><ShieldCheck size={17} /><span><strong>Анонимность включена</strong><small>Оценки хранятся отдельно от отметки участия.</small></span></div>
        </aside>

        <section className="main-content">
          {notice && <div className="notice notice-wide" role="status">{notice}<button aria-label="Закрыть уведомление" onClick={() => setNotice('')}><X size={15} /></button></div>}
          {user.role === 'staff' && (
            <section className="create-section">
              <div className="section-heading"><div><span className="eyebrow">НОВАЯ ЗАПИСЬ</span><h1>Создать опрос</h1></div><span className="quiet-tag"><Plus size={14} /> ЧЕРНОВИК</span></div>
              <form className="create-grid" onSubmit={createSurvey}>
                <label>Дисциплина<select value={newSurvey.subject_id} onChange={(event) => setNewSurvey({ ...newSurvey, subject_id: event.target.value })}><option value="1">Основы безопасных систем · 1</option><option value="2">Информационная безопасность · 2</option></select></label>
                <label>Преподаватель<select value={newSurvey.teacher_id} onChange={(event) => setNewSurvey({ ...newSurvey, teacher_id: event.target.value })}><option value="1">Иванов И. И. · 1</option><option value="2">Петрова А. С. · 2</option></select></label>
                <label>Начало периода<input type="date" value={newSurvey.period_start} onChange={(event) => setNewSurvey({ ...newSurvey, period_start: event.target.value })} required /></label>
                <label>Конец периода<input type="date" value={newSurvey.period_end} onChange={(event) => setNewSurvey({ ...newSurvey, period_end: event.target.value })} required /></label>
                <button className="button button-green create-submit" disabled={busy}>Создать черновик <Plus size={16} /></button>
              </form>
            </section>
          )}

          {!selectedId || !surveyDetails ? (
            <section className="empty-state"><div className="empty-icon"><ClipboardList size={25} /></div><span className="eyebrow">{user.role === 'staff' ? 'ОБЗОР ОПРОСОВ' : 'АКТИВНЫЕ ОПРОСЫ'}</span><h2>Выберите анкету<br />из списка слева.</h2><p>Детали и доступные действия появятся здесь.</p></section>
          ) : (
            <article className="detail-view">
              <div className="detail-kicker"><span className={`status-pill ${surveyDetails.status}`}>{surveyDetails.status === 'active' ? 'АКТИВЕН' : surveyDetails.status === 'closed' ? 'ЗАКРЫТ' : 'ЧЕРНОВИК'}</span><span>ОПРОС №{surveyDetails.id}</span></div>
              <div className="detail-title"><div><span className="eyebrow">ПРЕПОДАВАТЕЛЬ</span><h1>{surveyDetails.teacher_name}</h1><p>{surveyDetails.period_start} — {surveyDetails.period_end} <span className="separator">/</span> дисциплина #{surveyDetails.subject_id}</p></div><div className="teacher-stamp">{surveyDetails.teacher_name.split(' ').map((part) => part[0]).slice(0, 2).join('')}</div></div>
              {user.role === 'student' ? (
                <section className="vote-panel">
                  <div className="vote-heading"><div><span className="eyebrow">ТРИ КРИТЕРИЯ</span><h2>Ваша оценка</h2></div><span className="scale-note">ШКАЛА 2—5</span></div>
                  {surveyDetails.own_mark ? <div className="submitted-state"><span className="submitted-icon"><Check size={22} /></span><div><strong>Ответ уже принят</strong><p>Повторное голосование по этому опросу невозможно.</p></div></div> : (
                    <form onSubmit={submitVote}>
                      <RatingControl title="Качество материалов" value={ratings.rating_materials} onChange={(value) => setRatings({ ...ratings, rating_materials: value })} />
                      <RatingControl title="Ясность изложения" value={ratings.rating_clarity} onChange={(value) => setRatings({ ...ratings, rating_clarity: value })} />
                      <RatingControl title="Вовлечённость" value={ratings.rating_engagement} onChange={(value) => setRatings({ ...ratings, rating_engagement: value })} />
                      <button className="button button-green vote-submit" disabled={busy}>Отправить оценки <Send size={16} /></button>
                    </form>
                  )}
                </section>
              ) : (
                <section className="staff-panel">
                  <div className="staff-panel-head"><div><span className="eyebrow">ДЕЙСТВИЯ СОТРУДНИКА</span><h2>Статус и результаты</h2></div><BookOpen size={20} /></div>
                  <div className="action-row">
                    {surveyDetails.status === 'draft' && <button className="button button-green" onClick={() => changeStatus(surveyDetails, 'active')} disabled={busy}>Опубликовать <ArrowRight size={15} /></button>}
                    {surveyDetails.status === 'active' && <button className="button button-dark" onClick={() => changeStatus(surveyDetails, 'closed')} disabled={busy}>Закрыть опрос <X size={15} /></button>}
                    {surveyDetails.status === 'closed' && <button className="button button-outline" onClick={() => loadResults(surveyDetails.id)} disabled={busy}>Открыть агрегаты <Activity size={15} /></button>}
                    <button className="button button-outline" onClick={() => api(`/api/v1/surveys/${surveyDetails.id}/summaries`, { method: 'POST' }).then(() => setNotice('Задание поставлено в очередь')).catch((error) => setNotice(error.message))} disabled={busy}><Sparkles size={15} /> Характеристика</button>
                  </div>
                  {results && <div className="results-block"><div className="results-heading"><div><span className="eyebrow">АГРЕГИРОВАННЫЙ ОТЧЁТ</span><h3>{results.responses_count} ответов</h3></div><button className="icon-button export-button" title="Скачать CSV" aria-label="Скачать CSV" onClick={downloadResults}><ArrowDownToLine size={17} /></button></div><div className="metric-grid"><Metric label="Материалы" value={results.avg_materials} /><Metric label="Ясность" value={results.avg_clarity} /><Metric label="Вовлечённость" value={results.avg_engagement} /></div><Distribution data={results.distribution} /></div>}
                </section>
              )}
              <div className="anonymity-footnote"><CircleHelp size={16} /><span>Идентификатор участия используется только для защиты от повторного ответа и не связан со строкой оценок.</span></div>
            </article>
          )}
          <footer className="workspace-footer"><span>СЕРВИС КАЧЕСТВА ПРЕПОДАВАНИЯ</span><span>POSTGRESQL · REDIS · RABBITMQ</span></footer>
        </section>
      </div>
    </main>
  );
}

function RatingControl({ title, value, onChange }) {
  return <fieldset className="rating-control"><legend>{title}</legend><div className="rating-options">{[2, 3, 4, 5].map((rating) => <button type="button" key={rating} className={value === rating ? 'rating-option active' : 'rating-option'} aria-pressed={value === rating} onClick={() => onChange(rating)}>{rating}</button>)}</div><div className="rating-labels"><span>Низко</span><span>Высоко</span></div></fieldset>;
}

function Metric({ label, value }) {
  return <div className="metric"><span>{label}</span><strong>{Number(value).toFixed(2)}<small> / 5</small></strong><div className="metric-track"><span style={{ width: `${Math.min(Number(value) / 5 * 100, 100)}%` }} /></div></div>;
}

function Distribution({ data }) {
  return <div className="distribution"><span className="eyebrow">РАСПРЕДЕЛЕНИЕ ОЦЕНОК</span><div className="distribution-head"><span>Балл</span><span>Материалы</span><span>Ясность</span><span>Вовлечённость</span></div>{[2, 3, 4, 5].map((rating) => <div className="distribution-row" key={rating}><strong>{rating}</strong><span>{data[String(rating)]?.materials ?? 0}</span><span>{data[String(rating)]?.clarity ?? 0}</span><span>{data[String(rating)]?.engagement ?? 0}</span></div>)}</div>;
}

createRoot(document.getElementById('root')).render(<App />);
