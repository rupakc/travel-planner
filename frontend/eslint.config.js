import globals from 'globals'

export default [
  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.es2020,
      },
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
    },
    rules: {
      'no-unused-vars': 'off',
      'no-undef': 'off',
      // lucide-react exports icons whose names collide with JS/browser
      // globals. Importing them unaliased shadows the global for the whole
      // module — `new Map(...)` once constructed the Map *icon* and crashed
      // every multi-city search. Always import with an alias (Map as MapIcon).
      'no-restricted-syntax': ['error', {
        selector: "ImportDeclaration[source.value='lucide-react'] > ImportSpecifier[local.name=/^(Map|Image|History|Text|Option|Infinity|Navigation)$/]",
        message: 'This local name shadows a JS/browser global — alias the icon, e.g. `Map as MapIcon`.',
      }],
    },
  },
]
