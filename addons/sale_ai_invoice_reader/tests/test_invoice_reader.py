from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError
from unittest.mock import patch, MagicMock
import base64
import json


@tagged('post_install', '-at_install')
class TestInvoiceReader(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Clear existing keys/models to avoid test pollution from manual DB entries
        cls.env['gemini.api.key'].search([]).unlink()
        cls.env['gemini.model.priority'].search([]).unlink()
        # Create test customer and products
        cls.partner_a = cls.env['res.partner'].create({
            'name': 'Nguyễn Văn A',
            'phone': '0901234567',
        })
        cls.partner_b = cls.env['res.partner'].create({
            'name': 'Công ty TNHH Duy An',
            'phone': '0283848586',
        })
        cls.product_wood = cls.env['product.product'].create({
            'name': 'Bàn Gỗ Sồi Cao Cấp',
            'lst_price': 1000000,
        })
        cls.product_chair = cls.env['product.product'].create({
            'name': 'Ghế Xoay Văn Phòng',
            'lst_price': 500000,
        })

        # Create API keys
        cls.api_key_1 = cls.env['gemini.api.key'].create({
            'name': 'Primary Key',
            'key': 'primary_key_val',
            'sequence': 10,
            'is_active': True,
        })
        cls.api_key_2 = cls.env['gemini.api.key'].create({
            'name': 'Backup Key',
            'key': 'backup_key_val',
            'sequence': 20,
            'is_active': True,
        })

        # Create Model priorities
        cls.model_priority_1 = cls.env['gemini.model.priority'].create({
            'model_name': 'gemini-2.5-flash',
            'sequence': 10,
        })
        cls.model_priority_2 = cls.env['gemini.model.priority'].create({
            'model_name': 'gemini-2.0-flash',
            'sequence': 20,
        })

        cls.env['ir.config_parameter'].sudo().set_param('sale_ai_invoice_reader.gemini_system_prompt', 'System prompt instruction')
        cls.env['ir.config_parameter'].sudo().set_param('sale_ai_invoice_reader.gemini_api_rotation', 'True')
        cls.env['ir.config_parameter'].sudo().set_param('sale_ai_invoice_reader.last_api_key_id', '')

    def test_01_clean_phone(self):
        """Test phone normalization utility"""
        order = self.env['sale.order'].create({'partner_id': self.partner_a.id})
        self.assertEqual(order._clean_phone('+84901234567'), '0901234567')
        self.assertEqual(order._clean_phone('090 123 4567'), '0901234567')
        self.assertEqual(order._clean_phone('090-123-4567'), '0901234567')
        self.assertEqual(order._clean_phone(''), '')
        self.assertEqual(order._clean_phone(False), '')

    def test_02_partner_matching_phone_priority(self):
        """Test matching customer by phone number prioritizing exact matches"""
        order = self.env['sale.order'].create({
            'partner_id': self.partner_b.id,
            'invoice_file': base64.b64encode(b'dummy_file_data'),
            'invoice_filename': 'invoice.jpg'
        })

        # Setup mock data where phone matches Nguyễn Văn A (partner_a) but name is slightly different
        mock_response_data = {
            'candidates': [{
                'content': {
                    'parts': [{
                        'text': json.dumps({
                            'customer': {
                                'name': 'Nguyen Van A',
                                'phone': '0901234567',
                                'address': 'Hanoi'
                            },
                            'order_lines': [],
                            'total_amount': 0
                        })
                    }]
                }
            }]
        }

        with patch('requests.post') as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_response_data)
            action = order.action_read_invoice_ai()
            
            wizard = self.env['gemini.create.partner.wizard'].browse(action.get('res_id'))
            # Should match partner_a due to phone matching
            self.assertEqual(wizard.partner_id.id, self.partner_a.id)
            
            wizard.action_import_invoice()
            self.assertEqual(order.partner_id.id, self.partner_a.id)
            # The name 'Nguyen Van A' is very close to 'Nguyễn Văn A' (>70%), so no name warning should be here
            # But let's check warnings
            self.assertFalse(order.ai_analysis_warning)

    def test_03_partner_matching_phone_mismatch(self):
        """Test matching customer when phone number differs but name is similar"""
        order = self.env['sale.order'].create({
            'partner_id': self.partner_b.id,
            'invoice_file': base64.b64encode(b'dummy_file_data'),
            'invoice_filename': 'invoice.jpg'
        })

        mock_response_data = {
            'candidates': [{
                'content': {
                    'parts': [{
                        'text': json.dumps({
                            'customer': {
                                'name': 'Nguyễn Văn A',
                                'phone': '0999999999',  # Phone differs from partner_a's 0901234567
                                'address': 'Hanoi'
                            },
                            'order_lines': [],
                            'total_amount': 0
                        })
                    }]
                }
            }]
        }

        with patch('requests.post') as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_response_data)
            action = order.action_read_invoice_ai()
            
            wizard = self.env['gemini.create.partner.wizard'].browse(action.get('res_id'))
            # Nguyễn Văn A (partner_a) matches by name (since phone 0999999999 matches no one)
            self.assertEqual(wizard.partner_id.id, self.partner_a.id)
            
            wizard.action_import_invoice()
            self.assertEqual(order.partner_id.id, self.partner_a.id)
            # There should be a warning because the phone number doesn't match
            self.assertTrue(order.ai_analysis_warning)
            self.assertIn("không khớp với số trên hệ thống", order.ai_analysis_warning)

    def test_04_partner_not_found(self):
        """Test behavior when customer is completely missing in database"""
        order = self.env['sale.order'].create({
            'partner_id': self.partner_b.id,
            'invoice_file': base64.b64encode(b'dummy_file_data'),
            'invoice_filename': 'invoice.jpg'
        })

        mock_response_data = {
            'candidates': [{
                'content': {
                    'parts': [{
                        'text': json.dumps({
                            'customer': {
                                'name': 'Khách hàng lạ',
                                'phone': '0912222222',
                                'address': 'HCM'
                            },
                            'order_lines': [],
                            'total_amount': 0
                        })
                    }]
                }
            }]
        }

        with patch('requests.post') as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_response_data)
            action = order.action_read_invoice_ai()
            
            # Verify that act_window action for the wizard is returned
            self.assertEqual(action.get('res_model'), 'gemini.create.partner.wizard')
            
            # Instantiate the wizard and run action_only_import
            wizard = self.env['gemini.create.partner.wizard'].browse(action.get('res_id'))
            self.assertEqual(wizard.sale_order_id.id, order.id)
            self.assertEqual(wizard.partner_name, 'Khách hàng lạ')
            
            wizard.action_only_import()
            
            # Since user decided to only import, partner_id remains unchanged
            # But the warning field must warn that the customer is not found
            self.assertTrue(order.ai_analysis_warning)
            self.assertIn("Không tìm thấy khách hàng", order.ai_analysis_warning)

    def test_04_b_partner_create_wizard(self):
        """Test wizard customer creation option when customer is not found"""
        order = self.env['sale.order'].create({
            'partner_id': self.partner_b.id,
            'invoice_file': base64.b64encode(b'dummy_file_data'),
            'invoice_filename': 'invoice.jpg'
        })

        mock_response_data = {
            'candidates': [{
                'content': {
                    'parts': [{
                        'text': json.dumps({
                            'customer': {
                                'name': 'Khách hàng mới từ AI',
                                'phone': '0999888777',
                                'address': 'Da Nang'
                            },
                            'order_lines': [],
                            'total_amount': 0
                        })
                    }]
                }
            }]
        }

        with patch('requests.post') as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_response_data)
            action = order.action_read_invoice_ai()
            
            wizard = self.env['gemini.create.partner.wizard'].browse(action.get('res_id'))
            self.assertEqual(wizard.partner_name, 'Khách hàng mới từ AI')
            self.assertEqual(wizard.partner_phone, '0999888777')
            self.assertEqual(wizard.partner_address, 'Da Nang')
            
            wizard.action_create_partner_and_import()
            
            # Partner must be created, assigned to order, and details filled
            self.assertEqual(order.partner_id.name, 'Khách hàng mới từ AI')
            self.assertEqual(order.partner_id.phone, '0999888777')
            self.assertEqual(order.partner_id.street, 'Da Nang')

    def test_05_order_line_creation(self):
        """Test creation of order lines, finding existing products and leaving unknown ones blank"""
        order = self.env['sale.order'].create({
            'partner_id': self.partner_a.id,
            'invoice_file': base64.b64encode(b'dummy_file_data'),
            'invoice_filename': 'invoice.jpg'
        })

        mock_response_data = {
            'candidates': [{
                'content': {
                    'parts': [{
                        'text': json.dumps({
                            'customer': {
                                'name': 'Nguyễn Văn A',
                                'phone': '0901234567',
                                'address': 'Hanoi'
                            },
                            'order_lines': [
                                {
                                    'product_name': 'Bàn Gỗ Sồi Cao Cấp',  # Matches product_wood
                                    'quantity': 2,
                                    'price_unit': 950000,
                                    'subtotal': 1900000
                                },
                                {
                                    'product_name': 'Sản Phẩm Lạ Chưa Có',  # Matches nothing
                                    'quantity': 1,
                                    'price_unit': 120000,
                                    'subtotal': 120000
                                }
                            ],
                            'total_amount': 2020000
                        })
                    }]
                }
            }]
        }

        with patch('requests.post') as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_response_data)
            action = order.action_read_invoice_ai()
            
            wizard = self.env['gemini.create.partner.wizard'].browse(action.get('res_id'))
            wizard.action_import_invoice()

            self.assertEqual(len(order.order_line), 2)
            
            # First line: should match product_wood
            line1 = order.order_line[0]
            self.assertEqual(line1.product_id.id, self.product_wood.id)
            self.assertEqual(line1.product_uom_qty, 2)
            self.assertEqual(line1.price_unit, 950000)

            # Second line: should leave product_id as False and copy the product_name to description
            line2 = order.order_line[1]
            self.assertFalse(line2.product_id)
            self.assertEqual(line2.name, 'Sản Phẩm Lạ Chưa Có')
            self.assertEqual(line2.product_uom_qty, 1)
            self.assertEqual(line2.price_unit, 120000)

    def test_06_fallback_logic_execution(self):
        """Test the 2-tier fallback API execution logic"""
        order = self.env['sale.order'].create({
            'partner_id': self.partner_a.id,
            'invoice_file': base64.b64encode(b'dummy_file_data'),
            'invoice_filename': 'invoice.jpg'
        })

        mock_success_response = MagicMock(status_code=200, json=lambda: {
            'candidates': [{
                'content': {
                    'parts': [{
                        'text': json.dumps({
                            'customer': {'name': 'Nguyễn Văn A', 'phone': '0901234567', 'address': 'Hanoi'},
                            'order_lines': [],
                            'total_amount': 0
                        })
                    }]
                }
            }]
        })

        # Scenario 1: Primary Key + Primary Model fails with 429, but Fallback (Backup Key + Primary Model) succeeds
        with patch('requests.post') as mock_post:
            mock_post.side_effect = [
                MagicMock(status_code=429, text='Quota exceeded'),  # Primary fails
                mock_success_response                               # Backup key succeeds
            ]
            order.action_read_invoice_ai()
            self.assertEqual(mock_post.call_count, 2)
            # Verify the second call used backup key
            self.assertIn("key=backup_key_val", mock_post.call_args_list[1][0][0])
            self.assertIn("models/gemini-2.5-flash", mock_post.call_args_list[1][0][0])

        # Scenario 2: All combinations fail -> should raise UserError
        with patch('requests.post') as mock_post:
            mock_post.return_value = MagicMock(status_code=500, text='Internal Server Error')
            with self.assertRaises(UserError):
                order.action_read_invoice_ai()
            # 4 unique combinations: (Primary, Primary), (Backup, Primary), (Primary, Backup), (Backup, Backup)
            self.assertEqual(mock_post.call_count, 4)

    def test_07_rotation_logic(self):
        """Test round-robin rotation of API keys"""
        order = self.env['sale.order'].create({
            'partner_id': self.partner_a.id,
            'invoice_file': base64.b64encode(b'dummy_file_data'),
            'invoice_filename': 'invoice.jpg'
        })

        mock_success_response = MagicMock(status_code=200, json=lambda: {
            'candidates': [{
                'content': {
                    'parts': [{
                        'text': json.dumps({
                            'customer': {'name': 'Nguyễn Văn A', 'phone': '0901234567', 'address': 'Hanoi'},
                            'order_lines': [],
                            'total_amount': 0
                        })
                    }]
                }
            }]
        })

        # Clear last used api key id to start clean
        self.env['ir.config_parameter'].sudo().set_param('sale_ai_invoice_reader.last_api_key_id', '')

        with patch('requests.post') as mock_post:
            mock_post.return_value = mock_success_response
            order.action_read_invoice_ai()
            # First run: should use first key (primary_key_val) since no last used key is stored
            self.assertIn("key=primary_key_val", mock_post.call_args[0][0])
            self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('sale_ai_invoice_reader.last_api_key_id'), str(self.api_key_1.id))

        with patch('requests.post') as mock_post:
            mock_post.return_value = mock_success_response
            order.action_read_invoice_ai()
            # Second run: rotation is active and last key was key 1, so it should start with key 2 (backup_key_val)
            self.assertIn("key=backup_key_val", mock_post.call_args[0][0])
            self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('sale_ai_invoice_reader.last_api_key_id'), str(self.api_key_2.id))

    def test_08_reconciliation_modes(self):
        """Test order line reconciliation modes: append, replace, update"""
        order = self.env['sale.order'].create({
            'partner_id': self.partner_a.id,
            'invoice_file': base64.b64encode(b'dummy_file_data'),
            'invoice_filename': 'invoice.jpg'
        })

        # Pre-add an existing order line
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.product_wood.id,
            'name': self.product_wood.display_name,
            'product_uom_qty': 1,
            'price_unit': 1000,
        })

        mock_response_data = {
            'candidates': [{
                'content': {
                    'parts': [{
                        'text': json.dumps({
                            'customer': {
                                'name': 'Nguyễn Văn A',
                                'phone': '0901234567',
                                'address': 'Hanoi'
                            },
                            'order_lines': [
                                {
                                    'product_name': 'Bàn Gỗ Sồi Cao Cấp',
                                    'quantity': 2,
                                    'price_unit': 950000,
                                    'subtotal': 1900000
                                }
                            ],
                            'total_amount': 1900000
                        })
                    }]
                }
            }]
        }

        # 1. Test Mode: append
        with patch('requests.post') as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_response_data)
            action = order.action_read_invoice_ai()
            wizard = self.env['gemini.create.partner.wizard'].browse(action.get('res_id'))
            wizard.import_mode = 'append'
            wizard.action_import_invoice()
            
            # Should have the original line AND the new line
            self.assertEqual(len(order.order_line), 2)
            self.assertEqual(order.order_line[0].product_uom_qty, 1)
            self.assertEqual(order.order_line[0].price_unit, 1000)
            self.assertEqual(order.order_line[1].product_uom_qty, 2)
            self.assertEqual(order.order_line[1].price_unit, 950000)

        # Reset order lines back to a single original line
        order.order_line = [(5, 0, 0)]
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.product_wood.id,
            'name': self.product_wood.display_name,
            'product_uom_qty': 1,
            'price_unit': 1000,
        })

        # 2. Test Mode: replace
        with patch('requests.post') as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_response_data)
            action = order.action_read_invoice_ai()
            wizard = self.env['gemini.create.partner.wizard'].browse(action.get('res_id'))
            wizard.import_mode = 'replace'
            wizard.action_import_invoice()
            
            # Should delete original and keep only the new line
            self.assertEqual(len(order.order_line), 1)
            self.assertEqual(order.order_line[0].product_uom_qty, 2)
            self.assertEqual(order.order_line[0].price_unit, 950000)

        # Reset order lines back to a single original line
        order.order_line = [(5, 0, 0)]
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.product_wood.id,
            'name': self.product_wood.display_name,
            'product_uom_qty': 1,
            'price_unit': 1000,
        })

        # 3. Test Mode: update
        with patch('requests.post') as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_response_data)
            action = order.action_read_invoice_ai()
            wizard = self.env['gemini.create.partner.wizard'].browse(action.get('res_id'))
            wizard.import_mode = 'update'
            wizard.action_import_invoice()
            
            # Should update the existing line and NOT create a new one
            self.assertEqual(len(order.order_line), 1)
            self.assertEqual(order.order_line[0].product_uom_qty, 2)
            self.assertEqual(order.order_line[0].price_unit, 950000)


