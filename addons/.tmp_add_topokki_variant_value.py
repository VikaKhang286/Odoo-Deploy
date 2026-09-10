ProductTemplate = env['product.template'].sudo()
ProductAttributeValue = env['product.attribute.value'].sudo()

product_name = 'Xe bán Topokki Mr. Pokki có dù'
attribute_name = 'Giá trị biến thể'
new_value_name = 'Dù 1m6'

template = ProductTemplate.search([('name', '=', product_name)], limit=1)
if not template:
    raise RuntimeError(f'Không tìm thấy sản phẩm: {product_name}')

attribute_line = template.attribute_line_ids.filtered(
    lambda line: line.attribute_id.name == attribute_name
)[:1]
if not attribute_line:
    raise RuntimeError(f'Không tìm thấy thuộc tính: {attribute_name}')

value = ProductAttributeValue.search([
    ('attribute_id', '=', attribute_line.attribute_id.id),
    ('name', '=', new_value_name),
], limit=1)
if not value:
    value = ProductAttributeValue.create({
        'name': new_value_name,
        'attribute_id': attribute_line.attribute_id.id,
    })

if value.id not in attribute_line.value_ids.ids:
    attribute_line.write({'value_ids': [(4, value.id)]})

template.invalidate_recordset()
print(
    f'UPDATED template_id={template.id} line_id={attribute_line.id} '
    f'value_count={attribute_line.value_count} '
    f'values={attribute_line.value_ids.mapped("name")} '
    f'variants={template.product_variant_ids.ids}'
)
env.cr.commit()
