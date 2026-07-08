import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApplicationLog, AuthStatus, Campaign, LoginStatus } from "./api/client";

const AREA_OPTIONS = [
  { id: "", label: "Вся Россия" },
  { id: "1", label: "Москва" },
  { id: "2", label: "Санкт-Петербург" },
  { id: "3", label: "Екатеринбург" },
  { id: "4", label: "Новосибирск" },
  { id: "88", label: "Казань" },
];

function statusBadge(status: string) {
  const labels: Record<string, string> = {
    draft: "Черновик",
    running: "Запущена",
    completed: "Завершена",
    paused: "Остановлена",
    failed: "Ошибка",
  };
  return <span className={`badge ${status}`}>{labels[status] || status}</span>;
}

export default function App() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [loginStatus, setLoginStatus] = useState<LoginStatus | null>(null);
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [logs, setLogs] = useState<ApplicationLog[]>([]);
  const [message, setMessage] = useState<{ type: "success" | "error" | "info"; text: string } | null>(null);

  const [newName, setNewName] = useState("");
  const [newQuery, setNewQuery] = useState("");
  const [newArea, setNewArea] = useState("");
  const [newLimit, setNewLimit] = useState(10);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadAuth = useCallback(async () => {
    const status = await api.getAuthStatus();
    setAuth(status);
    return status;
  }, []);

  const loadCampaigns = useCallback(async () => {
    const items = await api.getCampaigns();
    setCampaigns(items);
    return items;
  }, []);

  const loadLogs = useCallback(async (id: number) => {
    const items = await api.getCampaignLogs(id);
    setLogs(items);
  }, []);

  useEffect(() => {
    loadAuth();
    loadCampaigns();
  }, [loadAuth, loadCampaigns]);

  useEffect(() => {
    const hasRunning = campaigns.some((c) => c.status === "running");
    if (hasRunning) {
      pollRef.current = setInterval(() => {
        loadCampaigns().then((items) => {
          if (selectedId) {
            const sel = items.find((c) => c.id === selectedId);
            if (sel) loadLogs(selectedId);
          }
        });
      }, 3000);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [campaigns, selectedId, loadCampaigns, loadLogs]);

  const pollLoginStatus = useCallback(async () => {
    const status = await api.getLoginStatus();
    setLoginStatus(status);
    if (status.state === "completed") {
      setMessage({ type: "success", text: "Вход выполнен! Сессия сохранена." });
      await loadAuth();
    } else if (status.state === "failed") {
      setMessage({ type: "error", text: status.error || "Ошибка входа" });
    }
    return status;
  }, [loadAuth]);

  const handleStartLogin = async () => {
    setMessage(null);
    try {
      const res = await api.startLogin();
      setMessage({ type: "info", text: res.message });
      const interval = setInterval(async () => {
        const st = await pollLoginStatus();
        if (st.state === "completed" || st.state === "failed" || st.state === "idle") {
          clearInterval(interval);
        }
      }, 1500);
    } catch (e) {
      setMessage({ type: "error", text: e instanceof Error ? e.message : "Ошибка" });
    }
  };

  const handleSubmitPhone = async () => {
    try {
      const res = await api.submitPhone(phone);
      setMessage({ type: "info", text: res.message });
      await pollLoginStatus();
    } catch (e) {
      setMessage({ type: "error", text: e instanceof Error ? e.message : "Ошибка" });
    }
  };

  const handleSubmitCode = async () => {
    try {
      const res = await api.submitCode(code);
      setMessage({ type: "info", text: res.message });
      await pollLoginStatus();
    } catch (e) {
      setMessage({ type: "error", text: e instanceof Error ? e.message : "Ошибка" });
    }
  };

  const handleDisconnect = async () => {
    await api.deleteSession();
    setAuth({ connected: false, session_file: "", message: "Войдите в аккаунт HH" });
    setMessage({ type: "success", text: "Сессия удалена" });
  };

  const handleCreateCampaign = async () => {
    if (!newName || !newQuery) {
      setMessage({ type: "error", text: "Заполните название и поисковый запрос" });
      return;
    }
    try {
      await api.createCampaign({
        name: newName,
        search_query: newQuery,
        area_id: newArea || undefined,
        apply_limit: newLimit,
      });
      setNewName("");
      setNewQuery("");
      setNewLimit(10);
      setMessage({ type: "success", text: "Кампания создана" });
      await loadCampaigns();
    } catch (e) {
      setMessage({ type: "error", text: e instanceof Error ? e.message : "Ошибка" });
    }
  };

  const handleStartCampaign = async (id: number) => {
    try {
      await api.startCampaign(id);
      setMessage({ type: "success", text: "Кампания запущена" });
      await loadCampaigns();
      setSelectedId(id);
      loadLogs(id);
    } catch (e) {
      setMessage({ type: "error", text: e instanceof Error ? e.message : "Ошибка" });
    }
  };

  const handleStopCampaign = async (id: number) => {
    try {
      await api.stopCampaign(id);
      setMessage({ type: "info", text: "Кампания остановлена" });
      await loadCampaigns();
    } catch (e) {
      setMessage({ type: "error", text: e instanceof Error ? e.message : "Ошибка" });
    }
  };

  const handleDeleteCampaign = async (id: number) => {
    try {
      await api.deleteCampaign(id);
      if (selectedId === id) {
        setSelectedId(null);
        setLogs([]);
      }
      setMessage({ type: "success", text: "Кампания удалена" });
      await loadCampaigns();
    } catch (e) {
      setMessage({ type: "error", text: e instanceof Error ? e.message : "Ошибка" });
    }
  };

  const selected = campaigns.find((c) => c.id === selectedId);
  const showLoginForm =
    loginStatus &&
    ["waiting_phone", "waiting_code", "starting"].includes(loginStatus.state);

  return (
    <div className="app">
      <header>
        <h1>HH AutoApply</h1>
        <p>Массовые автоотклики на hh.ru через парсинг</p>
      </header>

      {message && (
        <div className={`alert ${message.type}`}>{message.text}</div>
      )}

      <div className="card">
        <h2>Аккаунт HH</h2>
        {auth && (
          <span className={`badge ${auth.connected ? "connected" : "disconnected"}`}>
            {auth.connected ? "Подключён" : "Не подключён"}
          </span>
        )}
        {auth?.message && !auth.connected && (
          <p style={{ marginTop: 12, color: "var(--text-muted)", fontSize: "0.9rem" }}>
            {auth.message}
          </p>
        )}

        {!auth?.connected && !showLoginForm && (
          <div className="btn-group">
            <button className="btn btn-primary" onClick={handleStartLogin}>
              Войти в аккаунт
            </button>
          </div>
        )}

        {showLoginForm && (
          <div className="login-flow" style={{ marginTop: 16 }}>
            {loginStatus?.state === "waiting_phone" && (
              <>
                <label>Номер телефона</label>
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="+7 999 123-45-67"
                />
                <button className="btn btn-primary" onClick={handleSubmitPhone}>
                  Отправить
                </button>
              </>
            )}
            {loginStatus?.state === "waiting_code" && (
              <>
                <label>Код из SMS</label>
                <input
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="1234"
                />
                <button className="btn btn-primary" onClick={handleSubmitCode}>
                  Подтвердить
                </button>
              </>
            )}
            {loginStatus?.state === "starting" && (
              <p style={{ color: "var(--text-muted)" }}>Инициализация браузера...</p>
            )}
          </div>
        )}

        {auth?.connected && (
          <div className="btn-group">
            <button className="btn btn-danger" onClick={handleDisconnect}>
              Выйти
            </button>
          </div>
        )}
      </div>

      {auth?.connected && (
        <>
          <div className="card">
            <h2>Новая кампания</h2>
            <div className="form-grid">
              <div>
                <label>Название</label>
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Python разработчик — Москва"
                />
              </div>
              <div>
                <label>Лимит откликов</label>
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={newLimit}
                  onChange={(e) => setNewLimit(Number(e.target.value))}
                />
              </div>
              <div className="full">
                <label>Поисковый запрос</label>
                <input
                  value={newQuery}
                  onChange={(e) => setNewQuery(e.target.value)}
                  placeholder="Python разработчик"
                />
              </div>
              <div>
                <label>Регион</label>
                <select
                  value={newArea}
                  onChange={(e) => setNewArea(e.target.value)}
                  style={{
                    width: "100%",
                    padding: "10px 12px",
                    background: "var(--bg)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    color: "var(--text)",
                  }}
                >
                  {AREA_OPTIONS.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="btn-group">
              <button className="btn btn-primary" onClick={handleCreateCampaign}>
                Создать кампанию
              </button>
            </div>
          </div>

          <div className="card">
            <h2>Кампании ({campaigns.length})</h2>
            {campaigns.length === 0 ? (
              <p style={{ color: "var(--text-muted)" }}>
                Создайте кампанию для начала автооткликов
              </p>
            ) : (
              <div className="campaign-list">
                {campaigns.map((c) => (
                  <div
                    key={c.id}
                    className={`campaign-item ${selectedId === c.id ? "active" : ""}`}
                    onClick={() => {
                      setSelectedId(c.id);
                      loadLogs(c.id);
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <h3>{c.name}</h3>
                      {statusBadge(c.status)}
                    </div>
                    <div className="campaign-meta">
                      <span>Запрос: «{c.search_query}»</span>
                      <span>Лимит: {c.apply_limit}</span>
                      <span>Обработано: {c.processed_count}/{c.apply_limit}</span>
                    </div>

                    {c.status === "running" && (
                      <div className="progress-bar">
                        <div
                          className="progress-bar-fill"
                          style={{ width: `${Math.min(100, (c.processed_count / c.apply_limit) * 100)}%` }}
                        />
                      </div>
                    )}

                    <div className="stats-row">
                      <div className="stat sent">
                        <div className="stat-value">{c.sent_count}</div>
                        <div className="stat-label">Отправлено</div>
                      </div>
                      <div className="stat skipped">
                        <div className="stat-value">{c.skipped_count}</div>
                        <div className="stat-label">Пропущено</div>
                      </div>
                      <div className="stat failed">
                        <div className="stat-value">{c.failed_count}</div>
                        <div className="stat-label">Ошибки</div>
                      </div>
                    </div>

                    {c.error_message && (
                      <p style={{ color: "var(--danger)", fontSize: "0.85rem", marginTop: 8 }}>
                        {c.error_message}
                      </p>
                    )}

                    <div className="btn-group" onClick={(e) => e.stopPropagation()}>
                      {c.status !== "running" && (
                        <button className="btn btn-primary" onClick={() => handleStartCampaign(c.id)}>
                          {c.status === "paused" ? "Продолжить" : "Запустить"}
                        </button>
                      )}
                      {c.status === "running" && (
                        <button className="btn btn-secondary" onClick={() => handleStopCampaign(c.id)}>
                          Остановить
                        </button>
                      )}
                      {c.status !== "running" && (
                        <button className="btn btn-danger" onClick={() => handleDeleteCampaign(c.id)}>
                          Удалить
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {selected && logs.length > 0 && (
            <div className="card">
              <h2>Лог откликов — {selected.name}</h2>
              <table className="log-table">
                <thead>
                  <tr>
                    <th>Статус</th>
                    <th>Вакансия</th>
                    <th>Детали</th>
                    <th>Время</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((log) => (
                    <tr key={log.id}>
                      <td>
                        <span className={`status-dot ${log.status}`} />
                        {log.status === "success" ? "Отправлен" : log.status === "skipped" ? "Пропущен" : "Ошибка"}
                      </td>
                      <td>
                        <a
                          href={`https://hh.ru/vacancy/${log.vacancy_id}`}
                          target="_blank"
                          rel="noreferrer"
                          style={{ color: "var(--accent)" }}
                        >
                          {log.vacancy_title || log.vacancy_id}
                        </a>
                      </td>
                      <td style={{ color: "var(--text-muted)" }}>{log.detail}</td>
                      <td style={{ color: "var(--text-muted)" }}>
                        {new Date(log.created_at).toLocaleString("ru-RU")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
