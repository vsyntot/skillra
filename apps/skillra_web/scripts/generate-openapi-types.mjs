import fs from 'node:fs'

const [, , inputPath = 'openapi.json', outputPath = 'src/api/generated.d.ts'] = process.argv
const spec = JSON.parse(fs.readFileSync(inputPath, 'utf8'))

function refName(ref) {
  return ref.split('/').at(-1)
}

function schemaToTs(schema) {
  if (!schema) return 'unknown'
  if (schema.$ref) return `components["schemas"]["${refName(schema.$ref)}"]`
  if (schema.anyOf) {
    return schema.anyOf.map(schemaToTs).join(' | ')
  }
  if (schema.oneOf) {
    return schema.oneOf.map(schemaToTs).join(' | ')
  }
  if (schema.allOf) {
    return schema.allOf.map(schemaToTs).join(' & ')
  }
  if (schema.enum) {
    return schema.enum.map((value) => JSON.stringify(value)).join(' | ')
  }

  switch (schema.type) {
    case 'array':
      return `${schemaToTs(schema.items)}[]`
    case 'boolean':
      return 'boolean'
    case 'integer':
    case 'number':
      return 'number'
    case 'object':
      return objectToTs(schema)
    case 'string':
      return 'string'
    case 'null':
      return 'null'
    default:
      return schema.properties ? objectToTs(schema) : 'unknown'
  }
}

function objectToTs(schema) {
  const properties = schema.properties ?? {}
  const required = new Set(schema.required ?? [])
  const lines = Object.entries(properties).map(([key, value]) => {
    const optional = required.has(key) ? '' : '?'
    return `      ${JSON.stringify(key)}${optional}: ${schemaToTs(value)}`
  })
  if (lines.length) return `{\n${lines.join('\n')}\n    }`
  if (schema.additionalProperties && typeof schema.additionalProperties === 'object') {
    return `Record<string, ${schemaToTs(schema.additionalProperties)}>`
  }
  return 'Record<string, unknown>'
}

function responseType(operation) {
  const responses = operation.responses ?? {}
  const ok = responses['200'] ?? responses['201'] ?? responses['204'] ?? Object.values(responses)[0]
  const content = ok?.content?.['application/json']
  return content?.schema ? schemaToTs(content.schema) : 'unknown'
}

function parametersToTs(operation) {
  const grouped = {}
  for (const parameter of operation.parameters ?? []) {
    const location = parameter.in
    grouped[location] ??= []
    grouped[location].push(parameter)
  }

  const groups = Object.entries(grouped).map(([location, parameters]) => {
    const lines = parameters.map((parameter) => {
      const optional = parameter.required ? '' : '?'
      return `        ${JSON.stringify(parameter.name)}${optional}: ${schemaToTs(parameter.schema)}`
    })
    return `      ${location}: {\n${lines.join('\n')}\n      }`
  })

  return groups.length ? `{\n${groups.join('\n')}\n    }` : 'never'
}

const schemaEntries = Object.entries(spec.components?.schemas ?? {}).map(([name, schema]) => {
  return `    ${JSON.stringify(name)}: ${schemaToTs(schema)}`
})

const pathEntries = Object.entries(spec.paths ?? {}).map(([path, pathItem]) => {
  const operations = Object.entries(pathItem)
    .filter(([method]) => ['get', 'post', 'put', 'patch', 'delete'].includes(method))
    .map(([method, operation]) => {
      return `    ${method}: {
      parameters: ${parametersToTs(operation)}
      responses: {
        200: ${responseType(operation)}
      }
    }`
    })
  return `  ${JSON.stringify(path)}: {\n${operations.join('\n')}\n  }`
})

const output = `/**
 * Generated from FastAPI OpenAPI schema.
 * Run \`npm run generate:api\` to update.
 */
export interface paths {
${pathEntries.join('\n')}
}

export interface components {
  schemas: {
${schemaEntries.join('\n')}
  }
}
`

fs.writeFileSync(outputPath, output)
