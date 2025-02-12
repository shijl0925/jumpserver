import importlib

from collections import OrderedDict

from rest_framework.generics import ListAPIView, GenericAPIView
from rest_framework.response import Response
from rest_framework.exceptions import APIException
from rest_framework import status
from django.utils.translation import gettext_lazy as _

from common.sdk.sms import BACKENDS
from common.exceptions import JMSException
from settings.serializers.sms import SMSBackendSerializer
from settings.models import Setting

from .. import serializers


class SMSBackendAPI(ListAPIView):
    serializer_class = SMSBackendSerializer
    rbac_perms = {
        'list': 'settings.view_setting'
    }

    def list(self, request, *args, **kwargs):
        data = [
            {
                'name': b,
                'label': b.label
            }
            for b in BACKENDS.choices
        ]

        return Response(data)


class SMSTestingAPI(GenericAPIView):
    backends_serializer = {
        'alibaba': serializers.AlibabaSMSSettingSerializer,
        'tencent': serializers.TencentSMSSettingSerializer,
        'cmpp2': serializers.CMPP2SMSSettingSerializer
    }
    rbac_perms = {
        'POST': 'settings.change_sms'
    }

    @staticmethod
    def get_or_from_setting(key, value=''):
        if not value:
            secret = Setting.objects.filter(name=key).first()
            if secret:
                value = secret.cleaned_value

        return value or ''

    def get_alibaba_params(self, data):
        init_params = {
            'access_key_id': data['ALIBABA_ACCESS_KEY_ID'],
            'access_key_secret': self.get_or_from_setting(
                'ALIBABA_ACCESS_KEY_SECRET', data.get('ALIBABA_ACCESS_KEY_SECRET')
            )
        }
        send_sms_params = {
            'sign_name': data['ALIBABA_VERIFY_SIGN_NAME'],
            'template_code': data['ALIBABA_VERIFY_TEMPLATE_CODE'],
            'template_param': {'code': '666666'}
        }
        return init_params, send_sms_params

    def get_tencent_params(self, data):
        init_params = {
            'secret_id': data['TENCENT_SECRET_ID'],
            'secret_key': self.get_or_from_setting(
                'TENCENT_SECRET_KEY', data.get('TENCENT_SECRET_KEY')
            ),
            'sdkappid': data['TENCENT_SDKAPPID']
        }
        send_sms_params = {
            'sign_name': data['TENCENT_VERIFY_SIGN_NAME'],
            'template_code': data['TENCENT_VERIFY_TEMPLATE_CODE'],
            'template_param': OrderedDict(code='666666')
        }
        return init_params, send_sms_params

    def get_cmpp2_params(self, data):
        init_params = {
            'host': data['CMPP2_HOST'], 'port': data['CMPP2_PORT'],
            'sp_id': data['CMPP2_SP_ID'], 'src_id': data['CMPP2_SRC_ID'],
            'sp_secret': self.get_or_from_setting(
                'CMPP2_SP_SECRET', data.get('CMPP2_SP_SECRET')
            ),
            'service_id': data['CMPP2_SERVICE_ID'],
        }
        send_sms_params = {
            'sign_name': data['CMPP2_VERIFY_SIGN_NAME'],
            'template_code': data['CMPP2_VERIFY_TEMPLATE_CODE'],
            'template_param': OrderedDict(code='666666')
        }
        return init_params, send_sms_params

    def get_params_by_backend(self, backend, data):
        """
        返回两部分参数
            1、实例化参数
            2、发送测试短信参数
        """
        get_params_func = getattr(self, 'get_%s_params' % backend)
        return get_params_func(data)

    def post(self, request, backend):
        serializer_class = self.backends_serializer.get(backend)
        if serializer_class is None:
            raise JMSException(_('Invalid SMS platform'))
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        test_phone = serializer.validated_data.get('SMS_TEST_PHONE')
        if not test_phone:
            raise JMSException(code='test_phone_required', detail=_('test_phone is required'))

        init_params, send_sms_params = self.get_params_by_backend(backend, serializer.validated_data)

        m = importlib.import_module(f'common.sdk.sms.{backend}', __package__)
        try:
            client = m.client(**init_params)
            client.send_sms(
                phone_numbers=[test_phone],
                **send_sms_params
            )
            status_code = status.HTTP_200_OK
            data = {'msg': _('Test success')}
        except APIException as e:
            try:
                error = e.detail['errmsg']
            except:
                error = e.detail
            status_code = status.HTTP_400_BAD_REQUEST
            data = {'error': error}
        return Response(status=status_code, data=data)
