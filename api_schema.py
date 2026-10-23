"""OpenAPI contract for the local ZaloFlow API, importable in Postman."""
from copy import deepcopy


def build_schema():
    integer={'type':'integer','minimum':1,'maximum':9223372036854775807}
    string={'type':'string'}
    page=[{'name':'page','in':'query','schema':dict(integer,default=1)},
          {'name':'per_page','in':'query','schema':dict(integer,maximum=100,default=50)}]
    group_path=[{'name':'group_id','in':'path','required':True,'schema':integer}]
    media_path=[{'name':'media_id','in':'path','required':True,'schema':integer}]
    ref=lambda name:{'$ref':'#/components/schemas/'+name}
    array=lambda item:{'type':'array','items':item}
    envelope=lambda data:{'type':'object','required':['status','error_code','message','data'],
        'properties':{'status':{'type':'integer'},'error_code':{'type':'integer'},'message':string,'data':data}}
    def response(data,code='200',binary=False):
        return {code:{'description':'Thành công','content':{('application/octet-stream' if binary else 'application/json'):{'schema':data if binary else envelope(data)}}},
                'default':{'description':'Lỗi yêu cầu, xác thực hoặc quyền truy cập','content':{'application/json':{'schema':ref('Error')}}}}
    def operation(summary,permission,data=None,parameters=(),request=None,status='200',multipart=False,binary=False):
        op={'summary':summary,'description':'Quyền cần có: '+permission+'.','security':[{'BearerAuth':[]}],
            'responses':response(data or {'type':'object'},status,binary)}
        if parameters:op['parameters']=deepcopy(parameters)
        if request:op['requestBody']={'required':True,'content':{('multipart/form-data' if multipart else 'application/json'):{'schema':request}}}
        return op
    def object_schema(properties,required=(),strict=False):
        result={'type':'object','properties':properties}
        if required:result['required']=list(required)
        if strict:result['additionalProperties']=False
        return result
    page_props={'total':{'type':'integer','minimum':0},'page':integer,'per_page':dict(integer,maximum=100)}
    group_create=object_schema({'name':dict(string,minLength=1,maxLength=80),'data_type':dict(string,enum=['all','phone','uid'],default='all'),
                                'color':dict(string,pattern='^#[0-9a-fA-F]{6}$',default='#6860f6')},['name'],True)
    group=object_schema({'id':integer,**group_create['properties'],'created_at':dict(string,nullable=True),'active_membership_count':{'type':'integer','minimum':0}})
    contact_props={'phone':{'oneOf':[dict(string),dict(integer)],'description':'Một số Việt Nam 10 chữ số bắt đầu 0 hoặc +84; khuyến nghị dùng chuỗi để giữ số 0 đầu.'},
                   'name':dict(string,maxLength=100),'zalo_id':dict(string,maxLength=100),'email':dict(string,maxLength=254),
                   **{f'info{i}':dict(string,maxLength=500) for i in range(1,6)}}
    contact_input=object_schema(contact_props,['phone'],True)
    contact=object_schema({**contact_props,'id':integer,'consent':{'type':'integer','enum':[0,1]},'data_source':string})
    media=object_schema({'id':integer,'filename':string,'mime':string,'size':{'type':'integer','minimum':0},
                         'width':dict(integer,nullable=True),'height':dict(integer,nullable=True),'created_at':string,
                         'group_id':dict(integer,nullable=True),'download_url':string})
    import_result=object_schema({'group_id':integer,**{name:{'type':'integer','minimum':0} for name in ['received_count','added_count','existing_count','invalid_count']},
        'invalid_rows':array(object_schema({'row':integer,'reason':string})), 'invalid_rows_truncated':{'type':'boolean'},'dry_run':{'type':'boolean'}})
    rows_input=object_schema({'data':{'type':'array','minItems':1,'maxItems':500,'items':{}},
        'consent':{'type':'boolean','default':False,'description':'Chỉ xác nhận true khi khách hàng mới đã đồng ý nhận tin. Không thay đổi hồ sơ cũ.'},
        'source_name':dict(string,maxLength=150,default=''),'dry_run':{'type':'boolean','default':False}},['data'],True)
    rows_input['properties']['data']['description']='Mỗi dòng hợp lệ theo ContactInput; dòng sai được đếm invalid_count, các dòng hợp lệ khác vẫn được thêm.'
    paths={
        '/api/v1/data-groups':{
            'get':operation('Lấy nhóm data','data:read',object_schema({'groups':array(ref('DataGroup')),**page_props}),
                            [*page,{'name':'search','in':'query','schema':dict(string,maxLength=200)}]),
            'post':operation('Tạo nhóm data','data:write',ref('DataGroup'),request=group_create,status='201')},
        '/api/v1/data-groups/{group_id}/members':{
            'get':operation('Lấy data trong nhóm','data:read',object_schema({'group_id':integer,'members':array(ref('Contact')),**page_props}),[*group_path,*page]),
            'post':operation('Thêm data theo số điện thoại','data:write',ref('ImportResult'),[*group_path,
                 {'name':'Idempotency-Key','in':'header','schema':dict(string,maxLength=128,pattern='^[A-Za-z0-9_.:-]+$'),
                  'description':'Giữ nguyên mã và nội dung khi thử lại. Mã đã dùng với nội dung khác trả 409. dry_run không lưu mã.'}],rows_input)},
        '/api/v1/media-groups':{
            'get':operation('Lấy nhóm Media','media:read',object_schema({'groups':array(ref('MediaGroup')),'total':{'type':'integer','minimum':0}})),
            'post':operation('Tạo nhóm Media','media:write',ref('MediaGroup'),request=object_schema({'name':dict(string,minLength=1,maxLength=80)},['name'],True),status='201')},
        '/api/v1/media':{
            'get':operation('Lấy danh sách Media','media:read',object_schema({'media':array(ref('Media')),**page_props}),[*page,
                {'name':'kind','in':'query','schema':dict(string,enum=['all','image','video','document'],default='all')},
                {'name':'q','in':'query','schema':dict(string,maxLength=120)}, {'name':'group_id','in':'query','schema':integer}]),
            'post':operation('Tải một tệp Media, tối đa 10 MB','media:write',ref('Media'),request=object_schema({
                'file':dict(string,format='binary',description='JPG/JPEG, PNG, WEBP, PDF hoặc MP4. Thư viện tối đa 1.000 tệp/tài khoản.'),'group_id':integer},['file']),status='201',multipart=True)},
        '/api/v1/media/{media_id}/file':{
            'get':operation('Tải tệp Media về','media:read',dict(string,format='binary'),media_path,binary=True)},
        '/api/v1/media/{media_id}':{
            'patch':operation('Chuyển nhóm Media, null để bỏ nhóm','media:write',ref('Media'),media_path,
                object_schema({'group_id':dict(integer,nullable=True)},['group_id'],True)),
            'delete':operation('Xóa hoặc ẩn tệp đang được chiến dịch sử dụng','media:write',object_schema({'id':integer,'retained_for_campaigns':{'type':'boolean'}}),media_path,
                object_schema({'confirm_delete':{'type':'boolean','enum':[True]}},['confirm_delete'],True))}
    }
    return {'openapi':'3.0.3','info':{'title':'ZaloFlow API','version':'1.0.0',
            'description':'API riêng của ZaloFlow. Tạo khóa tại /integrations. Quyền theo từng khóa và chủ tài khoản; không sử dụng username để chọn chủ dữ liệu. Không gửi tin hoặc tự chuyển tài khoản qua API này.'},
        'servers':[{'url':'/'}],'paths':paths,'components':{'securitySchemes':{
            'BearerAuth':{'type':'http','scheme':'bearer','description':'Khóa zf_… tạo tại API tích hợp; gửi bằng Authorization header.'}},
            'schemas':{'DataGroup':group,'ContactInput':contact_input,'Contact':contact,'ImportResult':import_result,
                       'Media':media,'MediaGroup':object_schema({'id':integer,'name':string}),
                       'Error':object_schema({'status':{'type':'integer'},'error_code':{'type':'integer'},'message':string,'data':{'type':'object','nullable':True}})}}}
