/**
 * StatMonitor - Cloudflare Worker Orchestrator (SPEC-11, SPEC-29 & SPEC-38)
 * 
 * Працює у двох режимах:
 * 1. HTTP Fetch: обробка запитів із дашборду Streamlit, вебхуків та ручних тригерів.
 * 2. Scheduled Cron Trigger: високоточний запуск за розкладом на Edge-інфраструктурі Cloudflare.
 * 
 * SPEC-38 Zero-Cost Orchestration Sync:
 * Перед відправкою dispatch у GitHub Actions виконує легкий HTTP-запит до Supabase REST API (/rest/v1/).
 * Якщо контрольних точок та подій для розрахунку немає — пропускає виклик Actions, зберігаючи 100% безкоштовного білінгу.
 */

export default {
  // 1. Обробка HTTP-запитів (Dashboard, cURL, Webhook)
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const hasAuthAttempt =
      url.searchParams.has("secret") ||
      url.searchParams.has("source") ||
      url.searchParams.has("force") ||
      request.headers.has("x-webhook-secret") ||
      request.method !== "GET";

    if (!hasAuthAttempt && (url.pathname === "/" || url.pathname === "/health")) {
      return new Response(JSON.stringify({
        status: "ok",
        service: "StatMonitor Cloudflare Worker",
        mode: "button_only",
        message: "Воркер активний. Cron вимкнено — запуск можливий лише з ?secret=... (кнопка '⚡ Запуск' у дашборді)."
      }), {
        status: 200,
        headers: { "Content-Type": "application/json; charset=utf-8" }
      });
    }

    const cleanVal = (v) => String(v || "").trim().replace(/^["']|["']$/g, "");
    const secret = cleanVal(url.searchParams.get("secret") || request.headers.get("x-webhook-secret"));
    const source = url.searchParams.get("source") || "external_webhook";
    const force = url.searchParams.get("force") === "true";

    // Перевірка секретного ключа авторизації
    const expectedSecret = cleanVal(env.SECRET_KEY || "ALTECsrs1989_");
    if (!secret || secret !== expectedSecret) {
      return new Response(JSON.stringify({
        error: "Unauthorized: Invalid secret",
        hint: "Перевірте, чи однаковий SECRET_KEY задано в Cloudflare Variables and secrets та Streamlit Secrets."
      }), {
        status: 401,
        headers: { "Content-Type": "application/json; charset=utf-8" }
      });
    }

    // Ручний або форсований запуск (з кнопки в Streamlit чи CLI)
    if (force || source === "dashboard_button" || source === "dashboard_error_alert" || source === "manual" || source === "ci_test") {
      const result = await triggerGitHubWorkflow(env, source);
      return new Response(JSON.stringify(result), {
        status: result.success ? 200 : (result.statusCode || 500),
        headers: { "Content-Type": "application/json" }
      });
    }

    // Автоматичний вебхук: перевіряємо через SPEC-38 Zero-Cost Gate
    const gate = await checkShouldRunSupabase(env);
    if (!gate.shouldRun) {
      console.log(`[Zero-Cost Gate] Пропуск запуску: ${gate.reason}`);
      return new Response(JSON.stringify({
        success: true,
        skipped: true,
        source: source,
        reason: gate.reason,
        timestamp: new Date().toISOString()
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    console.log(`[Zero-Cost Gate] Запуск дозволено: ${gate.reason}`);
    const result = await triggerGitHubWorkflow(env, source);
    return new Response(JSON.stringify({ ...result, gate_reason: gate.reason }), {
      status: result.success ? 200 : (result.statusCode || 500),
      headers: { "Content-Type": "application/json" }
    });
  },

  // 2. Варіант А: плановий Cron вимкнено (лише запуск по кнопці з дашборду)
  async scheduled(event, env, ctx) {
    console.log(`[Cloudflare Cron] Вимкнено (режим button_only). Ігноруємо розклад: ${event.cron || "manual"}`);
  }
};

/**
 * Перевіряє через Supabase REST API чи потрібен запуск GitHub Actions (SPEC-38 Zero-Cost Gate).
 */
async function checkShouldRunSupabase(env) {
  const supabaseUrl = env.SUPABASE_URL || env.SUPABASE_REST_URL;
  const supabaseKey = env.SUPABASE_KEY || env.SUPABASE_ANON_KEY || env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl || !supabaseKey) {
    // Якщо змінні Supabase не задані, безпечний fail-open: дозволяємо запуск
    return { shouldRun: true, reason: "Supabase credentials not configured in Worker, defaulting to run" };
  }

  const cleanUrl = supabaseUrl.replace(/\/+$/, "");
  const headers = {
    "apikey": supabaseKey,
    "Authorization": `Bearer ${supabaseKey}`,
    "Content-Type": "application/json",
    "Accept": "application/json"
  };

  const now = new Date();
  const tPast = new Date(now.getTime() - 25 * 60 * 1000).toISOString();
  const tFuture = new Date(now.getTime() + 7 * 60 * 1000).toISOString();
  const tDueSettle = new Date(now.getTime() - 85 * 60 * 1000).toISOString();

  try {
    // 1. Перевірка контрольних точок у scheduler_plan
    const planUrl = `${cleanUrl}/rest/v1/scheduler_plan?status=eq.PLANNED&target_time=gte.${tPast}&target_time=lte.${tFuture}&select=id,trigger_type,description,target_time&limit=1`;
    const planRes = await fetch(planUrl, { headers });
    if (planRes.ok) {
      const planItems = await planRes.json();
      if (Array.isArray(planItems) && planItems.length > 0) {
        return {
          shouldRun: true,
          reason: `Контрольна точка [${planItems[0].trigger_type}]: ${planItems[0].description || planItems[0].id}`
        };
      }
    }

    // 2. Перевірка ставок для термінового розрахунку (paper_bets)
    const betsUrl = `${cleanUrl}/rest/v1/paper_bets?status=eq.PENDING&commence_time=lte.${tDueSettle}&select=id,match_name&limit=1`;
    const betsRes = await fetch(betsUrl, { headers });
    if (betsRes.ok) {
      const betItems = await betsRes.json();
      if (Array.isArray(betItems) && betItems.length > 0) {
        return {
          shouldRun: true,
          reason: `Ставка #${betItems[0].id} (${betItems[0].match_name}) очікує негайного розрахунку`
        };
      }
    }

    // 3. Періодичний фоновий скан (system_heartbeat): якщо минуло >= 80 хвилин
    const hbUrl = `${cleanUrl}/rest/v1/system_heartbeat?service_name=eq.scheduler_run&select=last_ping_at&limit=1`;
    const hbRes = await fetch(hbUrl, { headers });
    if (hbRes.ok) {
      const hbItems = await hbRes.json();
      if (Array.isArray(hbItems) && hbItems.length > 0 && hbItems[0].last_ping_at) {
        const lastPing = new Date(hbItems[0].last_ping_at);
        const minsSince = (now.getTime() - lastPing.getTime()) / (60 * 1000);
        if (minsSince >= 80) {
          return {
            shouldRun: true,
            reason: `Періодичний скан ліній (минуло ${Math.round(minsSince)} хв з останнього опитування)`
          };
        }
      } else {
        return { shouldRun: true, reason: "Пульс scheduler_run відсутній, перший запуск" };
      }
    }

    // Жодна умова не спрацювала — це холостий тік. Зберігаємо 0 хвилин білінгу!
    return {
      shouldRun: false,
      reason: "Zero-cost gate: немає активних точок, ставок для розрахунку та планового сканування (0 хв білінгу)"
    };
  } catch (err) {
    console.error("[Zero-Cost Gate Error]:", err.message);
    return { shouldRun: true, reason: `Помилка перевірки Supabase: ${err.message}, аварійний запуск` };
  }
}

/**
 * Відправляє POST workflow_dispatch запит до GitHub Actions API
 */
async function triggerGitHubWorkflow(env, triggerSource) {
  const ghToken = env.GH_PAT || env.GITHUB_TOKEN;
  const ghRepo = env.GH_REPO || "vsymchak/StatMonitor";
  const ghWorkflow = env.GH_WORKFLOW || "scheduler.yml";
  const ghRef = env.GH_REF || "main";

  if (!ghToken) {
    console.error("Помилка: GH_PAT не налаштовано у секретах Cloudflare Worker.");
    return { success: false, error: "Missing GH_PAT in Cloudflare Worker environment" };
  }

  const endpoint = `https://api.github.com/repos/${ghRepo}/actions/workflows/${ghWorkflow}/dispatches`;

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Accept": "application/vnd.github+json",
        "Authorization": `Bearer ${ghToken}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "StatMonitor-Cloudflare-Worker"
      },
      body: JSON.stringify({
        ref: ghRef,
        inputs: {
          trigger_source: triggerSource
        }
      })
    });

    if (response.status === 204) {
      console.log(`[Success] Воркфлоу успішно поставлено в чергу GitHub Actions (джерело: ${triggerSource})`);
      return { success: true, message: `Workflow dispatched successfully from ${triggerSource}` };
    }

    const errText = await response.text();
    console.error(`[GitHub API Error] ${response.status}: ${errText}`);
    return { success: false, statusCode: response.status, error: errText };
  } catch (err) {
    console.error(`[Network Error] ${err.message}`);
    return { success: false, error: err.message };
  }
}
