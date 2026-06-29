const https = require('https');

const input = JSON.parse(process.argv[2]);
const provider = (process.env.LLM_PROVIDER || 'anthropic').trim().toLowerCase();

function requireEnv(name, aliases = []) {
  for (const key of [name, ...aliases]) {
    if (process.env[key]) return process.env[key];
  }
  console.error(`Missing ${[name, ...aliases].join(' or ')}. Create .env.local in the project root or export it before starting the app.`);
  process.exit(1);
}

function hasImageContent(messages) {
  return (messages || []).some(message => {
    const content = message?.content;
    if (typeof content === 'string') return content.includes('data:image/');
    if (!Array.isArray(content)) return false;
    return content.some(block => {
      if (!block || typeof block !== 'object') return false;
      if (block.type === 'image_url') return true;
      const url = block.image_url?.url || block.url || '';
      return typeof url === 'string' && url.includes('data:image/');
    });
  });
}

function buildAnthropicRequest() {
  const apiKey = requireEnv('ANTHROPIC_AUTH_TOKEN', ['ANTHROPIC_API_KEY']);
  const url = new URL(process.env.ANTHROPIC_BASE_URL || 'https://zode.qa.qima-inc.com/api/proxy/forward');
  const body = JSON.stringify({
    model: input.model,
    max_tokens: input.max_tokens || 1024,
    system: input.system || undefined,
    messages: input.messages,
    stream: Boolean(input.stream),
  });

  return {
    url,
    path: `${url.pathname}/v1/messages`,
    body,
    headers: {
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
      'content-length': Buffer.byteLength(body),
    },
    parseSsePayload: parseAnthropicSsePayload,
    extractBufferedText: extractAnthropicBufferedText,
  };
}

function buildOpenAICompatibleRequest() {
  const apiKey = requireEnv('BAILIAN_API_KEY', ['DASHSCOPE_API_KEY']);
  const url = new URL(process.env.BAILIAN_BASE_URL || 'https://dashscope.aliyuncs.com/compatible-mode/v1');
  const messages = input.system
    ? [{ role: 'system', content: input.system }, ...input.messages]
    : input.messages;
  const body = JSON.stringify({
    model: input.model,
    max_tokens: input.max_tokens || 1024,
    messages,
    stream: Boolean(input.stream),
  });

  return {
    url,
    path: `${url.pathname.replace(/\/$/, '')}/chat/completions`,
    body,
    headers: {
      'authorization': `Bearer ${apiKey}`,
      'content-type': 'application/json',
      'content-length': Buffer.byteLength(body),
    },
    parseSsePayload: parseOpenAISsePayload,
    extractBufferedText: extractOpenAIBufferedText,
  };
}

const containsImageContent = hasImageContent(input.messages);
if (containsImageContent && provider !== 'bailian' && provider !== 'dashscope') {
  console.error('Multimodal image input requires LLM_PROVIDER=bailian or dashscope');
  process.exit(1);
}

const requestConfig = provider === 'bailian' || provider === 'dashscope'
  ? buildOpenAICompatibleRequest()
  : buildAnthropicRequest();

function writeRecord(record) {
  process.stdout.write(`${JSON.stringify(record)}\n`);
}

function parseAnthropicSsePayload(payload, onText) {
  if (!payload || payload === '[DONE]') return;
  const parsed = JSON.parse(payload);
  if (parsed.type === 'content_block_delta' && parsed.delta?.text) {
    onText(parsed.delta.text);
  }
}

function parseOpenAISsePayload(payload, onText) {
  if (!payload || payload === '[DONE]') return;
  const parsed = JSON.parse(payload);
  const text = parsed.choices?.[0]?.delta?.content;
  if (text) onText(text);
}

function extractAnthropicBufferedText(data) {
  if (data.startsWith('event:')) {
    return extractTextFromSse(data, parseAnthropicSsePayload);
  }
  const parsed = JSON.parse(data);
  return (parsed.content || [])
    .filter(block => block.type === 'text')
    .map(block => block.text)
    .join('\n');
}

function extractOpenAIBufferedText(data) {
  if (data.startsWith('data:')) {
    return extractTextFromSse(data, parseOpenAISsePayload);
  }
  const parsed = JSON.parse(data);
  return parsed.choices?.[0]?.message?.content || '';
}

function extractTextFromSse(data, parsePayload) {
  let text = '';
  for (const line of data.split('\n')) {
    if (!line.startsWith('data: ')) continue;
    const payload = line.slice(6).trim();
    parsePayload(payload, chunk => text += chunk);
  }
  return text;
}

function handleStreamingResponse(res) {
  let buffer = '';
  let errorBody = '';

  res.on('data', chunk => {
    const text = chunk.toString('utf8');
    if (res.statusCode < 200 || res.statusCode >= 300) {
      errorBody += text;
      return;
    }

    buffer += text;
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';

    for (const part of parts) {
      for (const line of part.split('\n')) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6).trim();
        requestConfig.parseSsePayload(payload, delta => writeRecord({ type: 'delta', text: delta }));
      }
    }
  });

  res.on('end', () => {
    if (res.statusCode < 200 || res.statusCode >= 300) {
      console.error(errorBody);
      process.exit(1);
    }

    if (buffer.trim()) {
      for (const line of buffer.split('\n')) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6).trim();
        requestConfig.parseSsePayload(payload, delta => writeRecord({ type: 'delta', text: delta }));
      }
    }

    writeRecord({ type: 'done' });
  });
}

function handleBufferedResponse(res) {
  let data = '';
  res.on('data', chunk => data += chunk);
  res.on('end', () => {
    if (res.statusCode < 200 || res.statusCode >= 300) {
      console.error(data);
      process.exit(1);
    }
    process.stdout.write(requestConfig.extractBufferedText(data));
  });
}

const req = https.request({
  hostname: requestConfig.url.hostname,
  path: requestConfig.path,
  method: 'POST',
  headers: requestConfig.headers,
}, (res) => {
  if (input.stream) {
    handleStreamingResponse(res);
  } else {
    handleBufferedResponse(res);
  }
});

req.on('error', (err) => {
  console.error(err.message);
  process.exit(1);
});

req.write(requestConfig.body);
req.end();
