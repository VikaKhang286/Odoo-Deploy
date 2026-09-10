{
    'name': 'DAC OpenClaw Integration',
    'version': '1.0',
    'category': '1. Duy An ERP',
    'author': 'DAC Team',
    'sequence': 5,
    'summary': 'Outbound webhook layer cho OpenClaw AI agent integration',
    'description': """
DAC OpenClaw Integration Layer
==============================
Module tách riêng cho tích hợp OpenClaw AI agent:
- Outbound webhook dispatcher (Odoo → OpenClaw events)
- HMAC-SHA256 signature cho mọi event
- Retry strategy với exponential backoff
- Event log cho audit & replay
- Hook vào sale.order, page.fm.conversation, dac.work.task

Events:
- order.created, order.stage_changed
- conversation.new_message, conversation.assigned
- task.assigned, task.overdue
    """,
    'depends': ['base', 'dac_erp', 'CRM_DAC'],
    'installable': True,
    'auto_install': False,
    'application': False,
    'data': [
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        'views/outbound_webhook_log_views.xml',
        'views/menuitem.xml',
        'views/data_quality_views.xml',
    ],
    'license': 'LGPL-3',
}
