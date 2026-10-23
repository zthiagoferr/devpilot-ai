#!/usr/bin/env node
/**
 * Generates the runtime configuration consumed by the SPA.
 *
 * Usage:
 *   node scripts/write-config.mjs --api-base-url=https://api.example.com --base-path=/
 *
 * Values may also come from the API_BASE_URL and BASE_PATH environment
 * variables. The output is a classic script (not JSON) loaded before the
 * Angular bundle, so a single artifact can be deployed against several
 * environments without rebuilding.
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const DEFAULT_OUTPUT = resolve(dirname(fileURLToPath(import.meta.url)), '../public/config.js');

class UsageError extends Error {}

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--help' || argument === '-h') {
      values.help = true;
      continue;
    }
    if (!argument.startsWith('--')) {
      throw new UsageError(`Argumento inesperado: ${argument}`);
    }

    const withoutPrefix = argument.slice(2);
    const separator = withoutPrefix.indexOf('=');
    const name = separator === -1 ? withoutPrefix : withoutPrefix.slice(0, separator);
    let value = separator === -1 ? undefined : withoutPrefix.slice(separator + 1);

    if (value === undefined) {
      const next = argv[index + 1];
      if (next === undefined || next.startsWith('--')) {
        throw new UsageError(`O argumento --${name} exige um valor.`);
      }
      value = next;
      index += 1;
    }

    values[name] = value;
  }
  return values;
}

function normalizeBaseUrl(value) {
  const trimmed = (value ?? '').trim();
  if (trimmed === '') {
    return '';
  }

  let parsed;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new UsageError(`API_BASE_URL inválida: ${trimmed}`);
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new UsageError('API_BASE_URL deve usar http ou https.');
  }
  if (parsed.search !== '' || parsed.hash !== '') {
    throw new UsageError('API_BASE_URL não pode conter query string nem fragmento.');
  }

  return parsed.toString().replace(/\/+$/, '');
}

function normalizeBasePath(value) {
  const trimmed = (value ?? '').trim();
  if (trimmed === '' || trimmed === '/') {
    return '';
  }
  if (!trimmed.startsWith('/')) {
    throw new UsageError('BASE_PATH deve começar com "/".');
  }
  if (trimmed.includes('//') || trimmed.includes('..')) {
    throw new UsageError('BASE_PATH contém segmentos inválidos.');
  }
  return trimmed.replace(/\/+$/, '');
}

function serialize(config) {
  const json = JSON.stringify(config, null, 2);
  // `<` never belongs in a URL; escaping it keeps the generated file safe even
  // if it is ever inlined into an HTML document.
  return `window.DevPilotConfig = ${json.replace(/</g, '\\u003c')};\n`;
}

function printHelp() {
  process.stdout.write(
    [
      'Gera o config.js de runtime do DevPilot AI.',
      '',
      'Opções:',
      '  --api-base-url <url>   URL pública da API (http/https). Vazio desativa a API.',
      '  --base-path <path>     Caminho base do deploy (ex.: /devpilot).',
      '  --out <arquivo>        Destino (padrão: public/config.js).',
      '  --help                 Mostra esta ajuda.',
      '',
      'Variáveis de ambiente equivalentes: API_BASE_URL, BASE_PATH.',
      '',
    ].join('\n'),
  );
}

function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 2;
    return;
  }

  if (args.help) {
    printHelp();
    return;
  }

  try {
    const config = {
      apiBaseUrl: normalizeBaseUrl(args['api-base-url'] ?? process.env.API_BASE_URL ?? ''),
      basePath: normalizeBasePath(args['base-path'] ?? process.env.BASE_PATH ?? ''),
    };
    const output = args.out ? resolve(process.cwd(), args.out) : DEFAULT_OUTPUT;
    mkdirSync(dirname(output), { recursive: true });
    writeFileSync(output, serialize(config), 'utf8');
    process.stdout.write(`config.js gerado em ${output}\n`);
  } catch (error) {
    if (error instanceof UsageError) {
      process.stderr.write(`${error.message}\n`);
      process.exitCode = 2;
      return;
    }
    throw error;
  }
}

main();
