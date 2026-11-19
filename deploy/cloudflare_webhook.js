/**
 * Cloudflare Worker: StatMonitor External Trigger Webhook & Scheduled Cron
 * 
 * Безсерверний шлюз для миттєвого тригеру GitHub Actions workflow_dispatch
 * без затримок черг крону GitHub.
 * 
 * Працює у двох режимах:
 * 1. HTTP Fetch: обробка запитів із дашборду Streamlit (кнопка '⚡ Запуск') та вебхуків.
 * 2. Scheduled Cron Trigger: високоточний запуск за розкладом на Edge-інфраструктурі Cloudflare (кожні 5 хв).
 * 
 * Змінні / Секрети у Cloudflare Worker Settings -> Variables:
 * - GITHUB_TOKEN або GH_PAT: Personal Access Token з правами actions:write або repo
 * - SECRET_KEY: довільний секретний ключ для захисту вебхука
 * - GITHUB_REPO або GH_REPO: "vsymchak/StatMonitor" (за замовчуванням)
 * - GITHUB_WORKFLOW або GH_WORKFLOW: "scheduler.yml" (за замовчуванням)
 */

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
    const expectedSecret = env.SECRET_KEY;
    const providedSecret = url.searchParams.get("secret") || request.headers.get("x-webhook-secret");

    if (expectedSecret && providedSecret !== expectedSecret) {
      return new Response(JSON.stringify({ error: "Unauthorized: Invalid secret" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }

    const ref = url.searchParams.get("ref") || "main";
    const source = url.searchParams.get("source") || "external_webhook";

    const res = await dispatchWorkflow(env, source, ref);
    return new Response(JSON.stringify(res), {
      status: res.status || (res.success ? 200 : 500),
      headers: { "Content-Type": "application/json" },
    });
  },

  // 2. Обробка високоточного розкладу Cloudflare Cron Triggers (Every 5 minutes)
  async scheduled(event, env, ctx) {
    const cronSource = `cloudflare_cron_${(event.cron || '5m').replace(/\s+/g, '_')}`;
    console.log(`[Cloudflare Cron] Тригер розкладу: ${event.cron} о ${new Date().toISOString()}`);
    ctx.waitUntil(
      dispatchWorkflow(env, cronSource, "main").then(res => {
        if (!res.success) {
          console.error(`[Cloudflare Cron Error]:`, res.error);
        } else {
          console.log(`[Cloudflare Cron Success]:`, res.message);
        }
      })
    );
  },
};
