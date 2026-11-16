/**
 * Cloudflare Worker: StatMonitor External Trigger Webhook
 * 
 * Безсерверний шлюз для миттєвого тригеру GitHub Actions workflow_dispatch
 * без затримок черг крону GitHub.
 * 
 * Налаштування змінних у Cloudflare Worker Settings -> Variables:
 * - GITHUB_TOKEN: Personal Access Token з правами actions:write або repo
 * - SECRET_KEY: довільний секретний ключ для захисту вебхука
 * - GITHUB_REPO: "vsymchak/StatMonitor" (за замовчуванням)
 * - GITHUB_WORKFLOW: "scheduler.yml" (за замовчуванням)
 * 
 * Приклад виклику:
 * GET https://statmonitor-trigger.your-subdomain.workers.dev/?secret=YOUR_SECRET_KEY&source=cron_job_org
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 1. Перевірка секретного ключа
    const expectedSecret = env.SECRET_KEY;
    const providedSecret = url.searchParams.get("secret") || request.headers.get("x-webhook-secret");

    if (expectedSecret && providedSecret !== expectedSecret) {
      return new Response(JSON.stringify({ error: "Unauthorized: Invalid secret" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }

    const githubToken = env.GITHUB_TOKEN;
    if (!githubToken) {
      return new Response(JSON.stringify({ error: "Server misconfiguration: GITHUB_TOKEN is missing" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }

    const repo = env.GITHUB_REPO || "vsymchak/StatMonitor";
    const workflow = env.GITHUB_WORKFLOW || "scheduler.yml";
    const ref = url.searchParams.get("ref") || "main";
    const source = url.searchParams.get("source") || "external_webhook";

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
        return new Response(
          JSON.stringify({
            success: true,
            status: 204,
            message: `Workflow ${workflow} dispatched successfully for ${repo} on ref ${ref}`,
            source: source,
            timestamp: new Date().toISOString(),
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }
        );
      }

      const errorText = await ghResponse.text();
      return new Response(
        JSON.stringify({
          success: false,
          status: ghResponse.status,
          error: errorText,
        }),
        {
          status: ghResponse.status,
          headers: { "Content-Type": "application/json" },
        }
      );
    } catch (err) {
      return new Response(
        JSON.stringify({
          success: false,
          error: err.message,
        }),
        {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }
      );
    }
  },
};
