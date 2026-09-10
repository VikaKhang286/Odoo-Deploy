{
    'name': 'AI Invoice Reader',
    'version': '1.3',
    'category': 'Sales',
    'summary': 'Tích hợp tính năng AI Invoice Reader trực tiếp vào Đơn bán hàng',
    'description': 'Sử dụng Gemini API bóc tách dữ liệu hóa đơn đính kèm và điền vào sale.order.',
    'author': 'Antigravity AI',
    'depends': ['base', 'sale', 'sale_management', 'account', 'product', 'dac_erp', 'CRM_DAC'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/sale_order_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sale_ai_invoice_reader/static/src/css/backend/invoice_upload.css',
            'sale_ai_invoice_reader/static/src/xml/backend/invoice_upload_dialog.xml',
            'sale_ai_invoice_reader/static/src/js/backend/invoice_upload_dialog.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
