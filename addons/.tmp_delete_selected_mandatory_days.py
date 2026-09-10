MandatoryDay = env['hr.leave.mandatory.day'].sudo()
company = env['res.company'].sudo().search([('name', '=', 'YourCompany')], limit=1)
if not company:
    company = env.company

targets = [
    ('Tết', '2026-02-17', '2026-02-19'),
    ("Hùng Kings' Commemorations", '2026-04-26', '2026-04-26'),
    ('Company Celebration', '2026-09-01', '2026-09-01'),
    ('Vietnam National Day', '2026-09-02', '2026-09-02'),
]

for name, start_date, end_date in targets:
    records = MandatoryDay.search([
        ('name', '=', name),
        ('start_date', '=', start_date),
        ('end_date', '=', end_date),
        ('company_id', '=', company.id),
    ])
    print(f'DELETED count={len(records)} ids={records.ids} name={name} dates={start_date}..{end_date}')
    records.unlink()

env.cr.commit()

remaining = MandatoryDay.search([
    ('start_date', '>=', '2026-01-01'),
    ('start_date', '<=', '2026-12-31'),
    ('company_id', '=', company.id),
], order='start_date, end_date, id')
print('REMAINING:')
for record in remaining:
    print(f'id={record.id} name={record.name} dates={record.start_date}..{record.end_date}')