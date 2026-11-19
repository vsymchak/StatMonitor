/**
 * Cloudflare Worker: StatMonitor External Trigger Webhook & Scheduled Cron (SPEC-11, SPEC-29 & SPEC-38)
 * 
 * Безсерверний шлюз для високоточного тригеру GitHub Actions workflow_dispatch
 * із попередньою Zero-Cost Gate перевіркою через Supabase REST API (/rest/v1/).
 */

async function checkShouldRunSupabase(env) {
  const supabaseUrl = env.SUPABASE_URL || env.SUPABASE_REST_URL;
  const supabaseKey = env.SUPABASE_KEY || env.SUPABASE_ANON_KEY || env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl || !supabaseKey) {
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

    return {
      shouldRun: false,
      reason: "Zero-cost gate: немає активних точок, ставок для розрахунку та планового сканування (0 хв білінгу)"
    };
  } catch (err) {
    console.error("[Zero-Cost Gate Error]:", err.message);
    return { shouldRun: true, reason: `Помилка перевірки Supabase: ${err.message}, аварійний запуск` };
  }
}

async function dispatchWorkflow(env, source = "external_webhook", ref = "main") {
  const githubToken = env.GITHUB_TOKEN || env.GH_PAT;
  if (!githubToken) {
    return {
      success: false,
      status: 500,
      error: "Server misconfiguration: GITHUB_TOKEN or GH_PAT is missing in Cloudflare variables/secrets",
    };
  }

  const repo = env.GITHUB_REPO || env.GH_REPO || "vsymchak/StatMonitor";
  const workflow = env.GITHUB_WORKFLOW || env.GH_WORKFLOW || "scheduler.yml";
  const ghApiUrl = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;

  try {
    const ghResponse = await fetch(ghApiUrl, {
      method: "POST",
      headers: {
        "Accept": "application/vnd.github+json",
        "Authorization": `Bearer ${githubToken}`,
        "User-Agent": "StatMonitor-Cloudflare-Worker",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({
        ref: ref,
        inputs: {
          trigger_source: source,
        },
      }),
    });

    if (ghResponse.status === 204) {
      return {
        success: true,
        status: 200,
        message: `Workflow ${workflow} dispatched successfully for ${repo} on ref ${ref}`,
        source: source,
        timestamp: new Date().toISOString(),
      };
    }

    const errorText = await ghResponse.text();
    return {
      success: false,
      status: ghResponse.status,
      error: errorText,
    };
  } catch (err) {
    return {
      success: false,
      status: 500,
      error: err.message,
    };
  }
}

export default {
  // 1. Обробка HTTP-запитів (Dashboard кнопка '⚡ Запуск', webhook)
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Перевірка секретного ключа
    const expectedSecret = env.SECRET_KEY || "ALTECsrs1989_";
    const providedSecret = url.searchParams.get("secret") || request.headers.get("x-webhook-secret");

    if (expectedSecret && providedSecret !== expectedSecret) {
      return new Response(JSON.stringify({ error: "Unauthorized: Invalid secret" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }

    const ref = url.searchParams.get("ref") || "main";
    const source = url.searchParams.get("source") || "external_webhook";
    const force = url.searchParams.get("force") === "true";

    if (force || source === "dashboard_button" || source === "manual" || source === "ci_test") {
      const res = await dispatchWorkflow(env, source, ref);
      return new Response(JSON.stringify(res), {
        status: res.status || (res.success ? 200 : 500),
        headers: { "Content-Type": "application/json" },
      });
    }

    const gate = await checkShouldRunSupabase(env);
    if (!gate.shouldRun) {
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

    const res = await dispatchWorkflow(env, source, ref);
    return new Response(JSON.stringify({ ...res, gate_reason: gate.reason }), {
      status: res.status || (res.success ? 200 : 500),
      headers: { "Content-Type": "application/json" },
    });
  },

  // 2. Обробка високоточного розкладу Cloudflare Cron Triggers
  async scheduled(event, env, ctx) {
    const cronSource = `cloudflare_cron_${(event.cron || '5m').replace(/\s+/g, '_')}`;
    console.log(`[Cloudflare Cron] Тригер розкладу: ${event.cron} о ${new Date().toISOString()}`);
    ctx.waitUntil((async () => {
      const gate = await checkShouldRunSupabase(env);
      if (!gate.shouldRun) {
        console.log(`[Cloudflare Cron Gate] Пропуск запуску: ${gate.reason}`);
        return;
      }
      console.log(`[Cloudflare Cron Gate] Запуск воркфлоу: ${gate.reason}`);
      const res = await dispatchWorkflow(env, cronSource, "main");
      if (!res.success) {
        console.error(`[Cloudflare Cron Error]:`, res.error);
      } else {
        console.log(`[Cloudflare Cron Success]:`, res.message);
      }
    })());
  },
};
