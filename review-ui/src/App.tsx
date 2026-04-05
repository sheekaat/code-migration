import React, { useState, useEffect } from 'react';

// Types
interface ConversionResult {
  id: string;
  source_path: string;
  target_path: string;
  source_code: string;
  converted_code: string;
  status: 'validated' | 'needs_review' | 'approved' | 'failed';
  confidence: number;
  rules_applied: string[];
  semantic_issues: string[];
  review_notes: string;
}

interface WorkspaceSummary {
  id: string;
  repo_path: string;
  source_language: string;
  target_language: string;
  total_files: number;
  validated: number;
  needs_review: number;
  failed: number;
}

// ── Mock data for standalone demo ──────────────────────────────────────────
const MOCK_RESULTS: ConversionResult[] = [
  {
    id: '1',
    source_path: 'Controllers/CustomerController.cs',
    target_path: 'src/main/java/com/company/app/CustomerController.java',
    source_code: `[ApiController]
[Route("api/[controller]")]
public class CustomerController : ControllerBase
{
    private readonly ICustomerService _service;

    public CustomerController(ICustomerService service)
    {
        _service = service;
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetById(int id)
    {
        var customer = await _service.GetByIdAsync(id);
        if (customer == null) return NotFound();
        return Ok(customer);
    }

    [HttpPost]
    public async Task<IActionResult> Create([FromBody] CustomerDto dto)
    {
        var result = await _service.CreateAsync(dto);
        return CreatedAtAction(nameof(GetById), new { id = result.Id }, result);
    }
}`,
    converted_code: `package com.company.app;

import org.springframework.web.bind.annotation.*;
import org.springframework.http.ResponseEntity;
import java.util.Optional;

@RestController
@RequestMapping("/api/customer")
public class CustomerController {

    private final CustomerService service;

    public CustomerController(CustomerService service) {
        this.service = service;
    }

    @GetMapping("/{id}")
    public ResponseEntity<?> getById(@PathVariable int id) {
        Optional<Customer> customer = service.getById(id);
        return customer
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping
    public ResponseEntity<Customer> create(@RequestBody CustomerDto dto) {
        Customer result = service.create(dto);
        return ResponseEntity.created(URI.create("/api/customer/" + result.getId()))
            .body(result);
    }
}`,
    status: 'validated',
    confidence: 0.92,
    rules_applied: ['http_get_mapping', 'http_post_mapping', 'api_controller', 'from_body', 'route_annotation'],
    semantic_issues: [],
    review_notes: '',
  },
  {
    id: '2',
    source_path: 'Forms/CustomerForm.frm',
    target_path: 'src/components/CustomerForm.tsx',
    source_code: `Private Sub Form_Load()
    txtName.Text = ""
    txtEmail.Text = ""
    cboStatus.AddItem "Active"
    cboStatus.AddItem "Inactive"
End Sub

Private Sub cmdSave_Click()
    Dim customer As New CustomerClass
    customer.Name = txtName.Text
    customer.Email = txtEmail.Text
    If customer.Save() Then
        MsgBox "Saved successfully"
    Else
        MsgBox "Error saving customer"
    End If
End Sub`,
    converted_code: `import React, { useState, useEffect } from 'react';

interface CustomerFormProps {
  onSave?: (customer: Customer) => void;
}

const CustomerForm: React.FC<CustomerFormProps> = ({ onSave }) => {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState('Active');
  const [message, setMessage] = useState('');

  // TODO: Manual review required — original used COM CustomerClass
  const handleSave = async () => {
    try {
      const response = await fetch('/api/customer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, status }),
      });
      if (response.ok) {
        setMessage('Saved successfully');
        onSave?.(await response.json());
      } else {
        setMessage('Error saving customer');
      }
    } catch (err) {
      setMessage('Network error');
    }
  };

  return (
    <div className="customer-form">
      <input value={name} onChange={e => setName(e.target.value)} placeholder="Name" />
      <input value={email} onChange={e => setEmail(e.target.value)} placeholder="Email" />
      <select value={status} onChange={e => setStatus(e.target.value)}>
        <option>Active</option>
        <option>Inactive</option>
      </select>
      <button onClick={handleSave}>Save</button>
      {message && <p>{message}</p>}
    </div>
  );
};

export default CustomerForm;`,
    status: 'needs_review',
    confidence: 0.68,
    rules_applied: ['sub_to_function', 'dim_statement', 'if_then', 'end_if', 'msgbox'],
    semantic_issues: ['COM object CustomerClass requires manual REST API mapping'],
    review_notes: '',
  },
  {
    id: '3',
    source_path: 'Services/OrderService.cs',
    target_path: 'src/main/java/com/company/app/OrderService.java',
    source_code: `public class OrderService : IOrderService
{
    private readonly IOrderRepository _repo;

    public List<Order> GetByCustomer(int customerId)
    {
        return _repo.FindAll()
            .Where(o => o.CustomerId == customerId)
            .OrderByDescending(o => o.CreatedAt)
            .ToList();
    }
}`,
    converted_code: `package com.company.app;

import org.springframework.stereotype.Service;
import java.util.List;
import java.util.stream.Collectors;

@Service
public class OrderService {

    private final OrderRepository repo;

    public OrderService(OrderRepository repo) {
        this.repo = repo;
    }

    public List<Order> getByCustomer(int customerId) {
        return repo.findAll().stream()
            .filter(o -> o.getCustomerId() == customerId)
            .sorted((a, b) -> b.getCreatedAt().compareTo(a.getCreatedAt()))
            .collect(Collectors.toList());
    }
}`,
    status: 'approved',
    confidence: 0.95,
    rules_applied: ['linq_where', 'linq_to_list', 'string_type', 'list_type'],
    semantic_issues: [],
    review_notes: 'Reviewed and approved — LINQ to Stream conversion is correct.',
  },
];

const MOCK_SUMMARY: WorkspaceSummary = {
  id: 'ws-demo-001',
  repo_path: '/repos/legacy-crm',
  source_language: 'csharp / vb6',
  target_language: 'java_spring + react_js',
  total_files: 3,
  validated: 1,
  needs_review: 1,
  failed: 0,
};

// ── Status badge ────────────────────────────────────────────────────────────
const STATUS_STYLES: Record<string, React.CSSProperties> = {
  validated:    { background: '#d1fae5', color: '#065f46', border: '1px solid #6ee7b7' },
  needs_review: { background: '#fef3c7', color: '#92400e', border: '1px solid #fcd34d' },
  approved:     { background: '#dbeafe', color: '#1e40af', border: '1px solid #93c5fd' },
  failed:       { background: '#fee2e2', color: '#991b1b', border: '1px solid #fca5a5' },
};

const StatusBadge: React.FC<{ status: string }> = ({ status }) => (
  <span style={{
    ...STATUS_STYLES[status] || {},
    padding: '2px 10px', borderRadius: 12, fontSize: 12, fontWeight: 500,
  }}>
    {status.replace('_', ' ').toUpperCase()}
  </span>
);

const ConfidenceBar: React.FC<{ value: number }> = ({ value }) => {
  const color = value >= 0.85 ? '#10b981' : value >= 0.7 ? '#f59e0b' : '#ef4444';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: '#e5e7eb', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${value * 100}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 12, color, fontWeight: 500, minWidth: 36 }}>{(value * 100).toFixed(0)}%</span>
    </div>
  );
};

// ── Main App ────────────────────────────────────────────────────────────────
const App: React.FC = () => {
  const [results, setResults] = useState<ConversionResult[]>(MOCK_RESULTS);
  const [selected, setSelected] = useState<ConversionResult | null>(MOCK_RESULTS[0]);
  const [view, setView] = useState<'source' | 'converted'>('converted');
  const [notes, setNotes] = useState('');
  const [filter, setFilter] = useState<string>('all');

  const summary = MOCK_SUMMARY;

  useEffect(() => {
    if (selected) setNotes(selected.review_notes);
  }, [selected]);

  const filtered = filter === 'all' ? results : results.filter(r => r.status === filter);

  const handleApprove = () => {
    if (!selected) return;
    setResults(rs => rs.map(r => r.id === selected.id
      ? { ...r, status: 'approved', review_notes: notes }
      : r
    ));
    setSelected(s => s ? { ...s, status: 'approved', review_notes: notes } : null);
  };

  const handleReject = () => {
    if (!selected) return;
    setResults(rs => rs.map(r => r.id === selected.id
      ? { ...r, status: 'needs_review', review_notes: notes }
      : r
    ));
  };

  const approvedCount = results.filter(r => r.status === 'approved').length;
  const reviewCount   = results.filter(r => r.status === 'needs_review').length;
  const validCount    = results.filter(r => r.status === 'validated').length;

  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', display: 'flex', flexDirection: 'column', height: '100vh', background: '#f8fafc' }}>
      {/* Header */}
      <div style={{ background: '#1e293b', color: '#f8fafc', padding: '12px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <span style={{ fontWeight: 600, fontSize: 16 }}>Code Migration Platform</span>
          <span style={{ marginLeft: 12, fontSize: 12, color: '#94a3b8' }}>{summary.repo_path}</span>
        </div>
        <div style={{ display: 'flex', gap: 16, fontSize: 13 }}>
          <span style={{ color: '#10b981' }}>✅ {approvedCount + validCount} ready</span>
          <span style={{ color: '#f59e0b' }}>⚠️ {reviewCount} to review</span>
        </div>
      </div>

      {/* Summary bar */}
      <div style={{ background: '#fff', borderBottom: '1px solid #e2e8f0', padding: '10px 24px', display: 'flex', gap: 24, fontSize: 13 }}>
        <span><b>{summary.source_language}</b> → <b>{summary.target_language}</b></span>
        <span style={{ color: '#64748b' }}>{summary.total_files} files</span>
        {['all', 'validated', 'needs_review', 'approved', 'failed'].map(f => (
          <button key={f} onClick={() => setFilter(f)}
            style={{ background: filter === f ? '#3b82f6' : 'transparent', color: filter === f ? '#fff' : '#64748b',
              border: `1px solid ${filter === f ? '#3b82f6' : '#e2e8f0'}`, borderRadius: 6,
              padding: '2px 10px', cursor: 'pointer', fontSize: 12 }}>
            {f.replace('_', ' ')}
          </button>
        ))}
      </div>

      {/* Body */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* File list */}
        <div style={{ width: 280, borderRight: '1px solid #e2e8f0', background: '#fff', overflowY: 'auto' }}>
          {filtered.map(r => (
            <div key={r.id}
              onClick={() => setSelected(r)}
              style={{ padding: '12px 16px', borderBottom: '1px solid #f1f5f9', cursor: 'pointer',
                background: selected?.id === r.id ? '#eff6ff' : 'transparent' }}>
              <div style={{ fontSize: 12, fontWeight: 500, color: '#1e293b', marginBottom: 4 }}>
                {r.source_path.split('/').pop()}
              </div>
              <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 6 }}>{r.source_path}</div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <StatusBadge status={r.status} />
              </div>
              <div style={{ marginTop: 6 }}><ConfidenceBar value={r.confidence} /></div>
            </div>
          ))}
        </div>

        {/* Code panel */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {selected ? (
            <>
              {/* Toolbar */}
              <div style={{ background: '#fff', borderBottom: '1px solid #e2e8f0', padding: '10px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <span style={{ fontWeight: 500, fontSize: 13 }}>{selected.source_path}</span>
                  <span style={{ margin: '0 8px', color: '#94a3b8' }}>→</span>
                  <span style={{ fontSize: 12, color: '#3b82f6' }}>{selected.target_path}</span>
                </div>
                <button onClick={() => setView('source')}
                  style={{ padding: '4px 12px', borderRadius: 6, border: `1px solid ${view === 'source' ? '#3b82f6' : '#e2e8f0'}`,
                    background: view === 'source' ? '#eff6ff' : '#fff', color: view === 'source' ? '#3b82f6' : '#64748b', cursor: 'pointer', fontSize: 12 }}>
                  Source
                </button>
                <button onClick={() => setView('converted')}
                  style={{ padding: '4px 12px', borderRadius: 6, border: `1px solid ${view === 'converted' ? '#3b82f6' : '#e2e8f0'}`,
                    background: view === 'converted' ? '#eff6ff' : '#fff', color: view === 'converted' ? '#3b82f6' : '#64748b', cursor: 'pointer', fontSize: 12 }}>
                  Converted
                </button>
              </div>

              {/* Semantic issues */}
              {selected.semantic_issues.length > 0 && (
                <div style={{ background: '#fef3c7', borderBottom: '1px solid #fcd34d', padding: '8px 20px' }}>
                  {selected.semantic_issues.map((issue, i) => (
                    <div key={i} style={{ fontSize: 12, color: '#92400e' }}>⚠️ {issue}</div>
                  ))}
                </div>
              )}

              {/* Code view */}
              <div style={{ flex: 1, overflow: 'auto' }}>
                <pre style={{ margin: 0, padding: 20, fontSize: 12, lineHeight: 1.6, fontFamily: 'Consolas, monospace', background: '#0f172a', color: '#e2e8f0', minHeight: '100%' }}>
                  <code>{view === 'source' ? selected.source_code : selected.converted_code}</code>
                </pre>
              </div>

              {/* Review panel */}
              <div style={{ background: '#fff', borderTop: '1px solid #e2e8f0', padding: '12px 20px' }}>
                <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>Rules applied: {selected.rules_applied.slice(0, 4).join(', ')}{selected.rules_applied.length > 4 ? ` +${selected.rules_applied.length - 4} more` : ''}</div>
                    <textarea
                      value={notes}
                      onChange={e => setNotes(e.target.value)}
                      placeholder="Add review notes..."
                      style={{ width: '100%', height: 48, resize: 'none', border: '1px solid #e2e8f0', borderRadius: 6, padding: '6px 10px', fontSize: 12, fontFamily: 'system-ui' }}
                    />
                  </div>
                  <div style={{ display: 'flex', gap: 8, paddingTop: 20 }}>
                    <button onClick={handleReject}
                      style={{ padding: '8px 16px', borderRadius: 6, border: '1px solid #fca5a5', background: '#fee2e2', color: '#991b1b', cursor: 'pointer', fontSize: 13 }}>
                      Flag Review
                    </button>
                    <button onClick={handleApprove}
                      style={{ padding: '8px 16px', borderRadius: 6, border: '1px solid #6ee7b7', background: '#d1fae5', color: '#065f46', cursor: 'pointer', fontSize: 13, fontWeight: 500 }}>
                      ✓ Approve
                    </button>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>
              Select a file to review
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default App;
