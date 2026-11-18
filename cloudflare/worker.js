/**
 * StatMonitor - Cloudflare Worker Orchestrator (SPEC-11 & SPEC-29)
 * 
 * Працює у двох режимах:
 * 1. HTTP Fetch: обробка зовнішніх запитів із дашборду Streamlit, вебхуків та ручних тригерів.
 * 2. Scheduled Cron Trigger: високоточний запуск за розкладом на Edge-інфраструктурі Cloudflare (0 сек затримки).
 */

export default {
  // 1. Обробка HTTP-запитів (Dashboard, cURL, Webhook)
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const secret = url.searchParams.get("secret");
    const source = url.searchParams.get("source") || "external_webhook";

    // Перевірка секретного ключа авторизації
    const expectedSecret = env.SECRET_KEY || "ALTECsrs1989_";
    if (!secret || secret.trim() !== expectedSecret.trim()) {
      return new Response(JSON.stringify({ error: "Unauthorized: Invalid secret key" }), {
        status: 401,
        headers: { "Content-Type": "application/json" }
      });
    }

    // Запуск воркфлоу в GitHub Actions
    const result = await triggerGitHubWorkflow(env, source);
    return new Response(JSON.stringify(result), {
      status: result.success ? 200 : (result.statusCode || 500),
      headers: { "Content-Type": "application/json" }
    });
  },

  // 2. Високоточний розклад Cloudflare Cron Triggers (sec-level precision)
  async scheduled(event, env, ctx) {
    console.log(`[Cloudflare Cron] Тригер розкладу: ${event.cron} о ${new Date().toISOString()}`);
    ctx.waitUntil(triggerGitHubWorkflow(env, `cloudflare_cron_${event.cron.replace(/\s+/g, '_')}`));
  }
};

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
