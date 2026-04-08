"""
VB6 to React/TypeScript Conversion Templates

Templates for converting VB6 Forms to React components.
"""

from ingestion.file_type_registry import ComponentType
from conversion.template_base import ConversionTemplate


# ═══════════════════════════════════════════════════════════════════════════
# VB6 FORM → REACT COMPONENT TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

VB6_FORM_TO_REACT = ConversionTemplate(
    name="VB6 Form to React Component",
    source_type=ComponentType.FORM,
    target_type="React Functional Component",
    prompt_template="""Convert this VB6 Form to a React 18 functional component with TypeScript.

## Source (VB6 Form)
```vb6
{source_content}
```

## Conversion Rules

### UI Structure
- Convert VB6 controls to React JSX:
  - TextBox → <input type="text">
  - ComboBox → <select> or react-select
  - ListBox → <select multiple> or custom list component
  - CommandButton → <button>
  - Label → <label> or <span>
  - CheckBox → <input type="checkbox">
  - OptionButton → <input type="radio">
  - Frame/Panel → <div> with CSS
  - PictureBox → <img> or <div> with background-image
  - DataGrid → HTML table or react-table
  - Timer → useEffect with setInterval

### State Management
- Form-level variables → useState hooks
- Module-level globals → Context API or props
- Control values → controlled components (value + onChange)
- Form_Load → useEffect with empty dependency array []

### Event Handlers
- _Click → onClick handler
- _Change → onChange handler
- _KeyPress → onKeyDown/onKeyUp
- _DblClick → onDoubleClick
- _GotFocus → onFocus
- _LostFocus → onBlur

### Data Access
- ADODB Recordset → fetch() or axios with useEffect
- Field references → state variables
- MoveFirst/MoveNext → array iteration

### Error Handling
- On Error GoTo → try/catch blocks
- Error labels → separate error handler functions

### TypeScript Types
- Define interfaces for props and state
- Use proper TypeScript types for all variables
- Use union types where needed

### React Standards
- Functional components only (no class components)
- Use hooks for state and side effects
- Props interface with proper typing
- Export default at the end

### CRITICAL: Compilable Code Requirements
- NEVER use TODO comments or placeholder code
- NEVER leave event handlers empty
- ALWAYS provide complete working implementations
- ALL handlers must be defined functions, not inline

## Output Format
Return ONLY the complete React component code:
1. Imports (React, hooks, any libraries)
2. Interface definitions for props/state
3. Main component function
4. Event handler functions
5. useEffect for initialization
6. JSX return
7. Export statement

No markdown fences. No explanations. NO PLACEHOLDERS.
""",
    validation_rules=[
        "Must use functional component (not class)",
        "Must have useState for state management",
        "Must handle all original event handlers",
        "Must convert ADODB to fetch/API calls",
        "Must convert On Error to try/catch",
        "Must use TypeScript interfaces",
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# VB6 MODULE → JAVASCRIPT/TS UTILITIES TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

VB6_MODULE_TO_JS = ConversionTemplate(
    name="VB6 Module to JavaScript Utilities",
    source_type=ComponentType.MODULE,
    target_type="JavaScript/TypeScript Module",
    prompt_template="""Convert this VB6 Module (.bas file) to a JavaScript/TypeScript utility module.

## Source (VB6 Module)
```vb6
{source_content}
```

## Conversion Rules

### Function Conversion
- Public Sub/Function → export function
- Private Sub/Function → function (not exported)
- Parameters → function parameters with TypeScript types
- Return types → explicit TypeScript return types

### Variable Types
- Dim As String → const/let with string type
- Dim As Integer/Long → number type
- Dim As Boolean → boolean type
- Dim As Variant → any type (prefer specific)
- Arrays → TypeScript arrays (string[], number[])

### Control Structures
- If/Then/Else → if/else
- For/Next → for loop
- Do While/Until → while loop
- Select Case → switch statement
- With statement → object destructuring or direct property access

### VB6 Built-ins
- MsgBox → alert() or custom modal
- InputBox → prompt() or custom input modal
- Format → Intl.DateTimeFormat or toLocaleString
- Now → new Date()
- UCase/LCase → toUpperCase()/toLowerCase()
- Left/Right/Mid → slice(), substring()
- InStr → indexOf()
- Replace → replace()
- Trim → trim()
- Len → length property

### Error Handling
- On Error → try/catch blocks
- Err object → Error object
- Resume Next → careful error handling with fallback

### CRITICAL: Compilable Code Requirements
- NEVER use TODO comments or placeholder code
- NEVER leave function bodies empty
- ALWAYS provide complete working implementations
- Export all public functions

## Output Format
Return ONLY the complete JavaScript/TypeScript module:
1. Imports (if any external libraries needed)
2. Type definitions (interfaces, types)
3. Private helper functions
4. Exported public functions
5. Default export if appropriate

No markdown fences. No explanations. NO PLACEHOLDERS.
""",
    validation_rules=[
        "Must use TypeScript types for all functions",
        "Must export all public functions",
        "Must convert all VB6 built-in functions",
        "Must handle errors with try/catch",
    ],
)
