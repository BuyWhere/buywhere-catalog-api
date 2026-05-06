import { NextResponse } from 'next/server';

const catalog = {
  api: "BuyWhere Product Catalog API",
  version: "v1",
  description: "Agent-native product catalog API for AI agent commerce. Indexes 5M+ products from 40+ retailers across Southeast Asia, US, Australia, Japan, and Korea.",
  baseUrl: "https://api.buywhere.ai",
  auth: {
    type: "Bearer",
    keyPrefixes: {
      "bw_free_": { rateLimit: "60 req/min", tier: "free" },
      "bw_live_": { rateLimit: "600 req/min", tier: "production" },
      "bw_partner_": { rateLimit: "unlimited", tier: "partner" },
    },
    signUpUrl: "https://buywhere.ai/api-keys",
  },
  endpoints: {
    rest: {
      base: "https://api.buywhere.ai/v1",
      openApiSpec: "https://api.buywhere.ai/openapi.json",
    },
    mcp: {
      url: "https://api.buywhere.ai/mcp",
      protocol: "MCP",
      transport: "HTTP",
      guide: "https://buywhere.ai/docs/guides/mcp",
    },
    graphql: {
      url: "https://api.buywhere.ai/api/graphql",
    },
  },
  docs: {
    apiDocs: "https://api.buywhere.ai/docs",
    llmsTxt: "https://api.buywhere.ai/llms.txt",
    aiTxt: "https://api.buywhere.ai/ai.txt",
  },
  status: {
    health: "https://api.buywhere.ai/health",
    dashboard: "https://api.buywhere.ai/dashboard",
  },
};

export async function GET() {
  return NextResponse.json(catalog, {
    status: 200,
    headers: {
      'Cache-Control': 'public, max-age=3600, s-maxage=86400',
      'Access-Control-Allow-Origin': '*',
    },
  });
}

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    },
  });
}
